"""Платёжные флоу с моками БД: идемпотентность, план, продление, пакеты, промо, refund, рефералка."""
import datetime as dt
from types import SimpleNamespace

import handlers
import payments


# ----------------------------------------------------------------- фейки

class FakeMsg:
    def __init__(self):
        self.replies = []
        self.successful_payment = None

    async def reply_text(self, text, **kw):
        self.replies.append(text)


class FakeBot:
    def __init__(self):
        self.sent = []
        self.refunded = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))

    async def refund_star_payment(self, user_id, telegram_payment_charge_id):
        self.refunded.append((user_id, telegram_payment_charge_id))


def make_update(uid=1, lang="ru", args_text=None):
    msg = FakeMsg()
    user = SimpleNamespace(id=uid, username="u", language_code=lang)
    upd = SimpleNamespace(effective_user=user, message=msg, effective_message=msg)
    return upd, msg


def make_context(bot=None, args=None):
    return SimpleNamespace(bot=bot or FakeBot(), args=args or [],
                           user_data={}, application=SimpleNamespace())


class FakeDB:
    """In-memory заглушка БД для платёжной логики."""
    def __init__(self):
        self.charges = set()
        self.users = {1: dict(user_id=1, lang="ru", plan="free", premium_until=None,
                              sub_charge_id=None, credits=0, goal_mode="lose")}
        self.payments_log = []

    async def record_payment(self, uid, payload, amount, charge):
        if charge in self.charges:
            return False
        self.charges.add(charge)
        self.payments_log.append((uid, payload, amount, charge))
        return True

    async def set_plan(self, uid, plan):
        self.users[uid]["plan"] = plan

    async def set_premium_until(self, uid, until):
        self.users[uid]["premium_until"] = until

    async def grant_premium_days(self, uid, days):
        now = dt.datetime.now(dt.timezone.utc)
        base = self.users[uid]["premium_until"] or now
        self.users[uid]["premium_until"] = max(base, now) + dt.timedelta(days=days)

    async def set_sub_charge_id(self, uid, charge):
        self.users[uid]["sub_charge_id"] = charge

    async def add_credits(self, uid, n):
        self.users[uid]["credits"] += n

    async def get_user(self, uid):
        return self.users.get(uid)

    async def mark_refunded(self, charge):
        pass

    async def get_payment(self, charge):
        for uid, payload, amount, ch in self.payments_log:
            if ch == charge:
                return {"payload": payload}
        return None

    async def revoke_premium(self, uid):
        self.users[uid]["premium_until"] = dt.datetime.now(dt.timezone.utc)


def _patch_db(monkeypatch, fake):
    for name in ("record_payment", "set_plan", "set_premium_until", "grant_premium_days",
                 "set_sub_charge_id", "add_credits", "get_user", "mark_refunded",
                 "get_payment", "revoke_premium"):
        monkeypatch.setattr(payments.db, name, getattr(fake, name))


def _sp(payload, charge, amount=200, recurring=False, first=False, exp=None):
    return SimpleNamespace(invoice_payload=payload, telegram_payment_charge_id=charge,
                           total_amount=amount, is_recurring=recurring,
                           is_first_recurring=first, subscription_expiration_date=exp)


# ----------------------------------------------------------------- тесты

async def test_premium_payment_sets_plan(monkeypatch):
    fake = FakeDB(); _patch_db(monkeypatch, fake)
    upd, msg = make_update(); ctx = make_context()
    msg.successful_payment = _sp("premium_sub", "ch1")
    await payments.on_successful_payment(upd, ctx)
    assert fake.users[1]["plan"] == "premium"
    assert fake.users[1]["premium_until"] is not None
    assert len(msg.replies) == 1


async def test_payment_idempotent(monkeypatch):
    fake = FakeDB(); _patch_db(monkeypatch, fake)
    upd, msg = make_update(); ctx = make_context()
    msg.successful_payment = _sp("premium_macros_sub", "dup")
    await payments.on_successful_payment(upd, ctx)
    await payments.on_successful_payment(upd, ctx)  # повторная доставка
    assert len(fake.payments_log) == 1            # платёж записан один раз
    assert len(msg.replies) == 1                  # подтверждение одно


async def test_macros_plan_and_renewal(monkeypatch):
    fake = FakeDB(); _patch_db(monkeypatch, fake)
    upd, msg = make_update(); ctx = make_context()
    msg.successful_payment = _sp("premium_macros_sub", "m1", first=True, recurring=True)
    await payments.on_successful_payment(upd, ctx)
    assert fake.users[1]["plan"] == "premium_plus"
    # продление новым charge со сдвигом даты
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=60)
    upd2, msg2 = make_update(); ctx2 = make_context()
    upd2.message.successful_payment = _sp("premium_macros_sub", "m2", recurring=True, exp=future)
    await payments.on_successful_payment(upd2, ctx2)
    assert fake.users[1]["premium_until"] == future


async def test_pack_adds_credits(monkeypatch):
    fake = FakeDB(); _patch_db(monkeypatch, fake)
    upd, msg = make_update(); ctx = make_context()
    msg.successful_payment = _sp("credits:50", "p1", amount=70)
    await payments.on_successful_payment(upd, ctx)
    assert fake.users[1]["credits"] == 50


async def test_apply_promo_grants(monkeypatch):
    fake = FakeDB(); _patch_db(monkeypatch, fake)
    async def fake_redeem(uid, code, today):
        return {"ok": True, "kind": "premium_plus_days", "value": 7}
    monkeypatch.setattr(payments.db, "redeem_promo", fake_redeem)
    upd, msg = make_update(); ctx = make_context()
    await payments.apply_promo(upd, ctx, "PROMO")
    assert fake.users[1]["plan"] == "premium_plus"
    assert fake.users[1]["premium_until"] is not None


async def test_apply_promo_error(monkeypatch):
    fake = FakeDB(); _patch_db(monkeypatch, fake)
    async def fake_redeem(uid, code, today):
        return {"ok": False, "reason": "already"}
    monkeypatch.setattr(payments.db, "redeem_promo", fake_redeem)
    upd, msg = make_update(); ctx = make_context()
    await payments.apply_promo(upd, ctx, "X")
    assert any("❌" in r for r in msg.replies)


async def test_refund_revokes_premium(monkeypatch):
    import config
    monkeypatch.setattr(config, "ADMIN_IDS", {1})
    fake = FakeDB(); _patch_db(monkeypatch, fake)
    fake.payments_log.append((1, "premium_sub", 200, "ch9"))
    bot = FakeBot(); upd, msg = make_update(); ctx = make_context(bot=bot, args=["1", "ch9"])
    await payments.refund_cmd(upd, ctx)
    assert ("1", "ch9") in [(str(u), c) for u, c in bot.refunded] or (1, "ch9") in bot.refunded
    # Premium отозван (до now)
    assert fake.users[1]["premium_until"] <= dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=2)


async def test_referral_rewards_both(monkeypatch):
    payments._settings = {"mon": True, "free_daily": 3, "free_period": 30, "macros_tier": True,
                          "macros_price": 300, "ref_enabled": True, "ref_days": 30, "ref_needed": 1}
    granted = []
    referrals = set()

    async def add_referral(referrer, referred):
        if referred in referrals:
            return False
        referrals.add(referred); return True

    async def get_user(uid):
        return {"user_id": uid, "lang": "ru"}

    async def count_referrals(rid):
        return 1

    async def grant(uid, days):
        granted.append(uid)

    monkeypatch.setattr(handlers.db, "add_referral", add_referral)
    monkeypatch.setattr(handlers.db, "get_user", get_user)
    monkeypatch.setattr(handlers.db, "count_referrals", count_referrals)
    monkeypatch.setattr(handlers.db, "grant_referral_reward", grant)

    bot = FakeBot()
    upd, msg = make_update(uid=2); ctx = make_context(bot=bot, args=["ref_1"])
    await handlers._handle_referral(upd, ctx, inserted=True)
    assert 2 in granted and 1 in granted  # бонус другу и рефереру


async def test_referral_no_self(monkeypatch):
    payments._settings = {"mon": True, "free_daily": 3, "free_period": 30, "macros_tier": True,
                          "macros_price": 300, "ref_enabled": True, "ref_days": 30, "ref_needed": 1}
    called = []
    async def add_referral(a, b): called.append(1); return True
    monkeypatch.setattr(handlers.db, "add_referral", add_referral)
    upd, msg = make_update(uid=5); ctx = make_context(args=["ref_5"])  # сам себя
    await handlers._handle_referral(upd, ctx, inserted=True)
    assert not called  # самоприглашение игнорируется
