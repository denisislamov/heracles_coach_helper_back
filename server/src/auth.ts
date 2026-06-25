import type { NextFunction, Request, Response } from 'express';
import jwt from 'jsonwebtoken';
import { env } from './env.js';

export interface AdminClaims {
  sub: string;
  email: string;
}

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      admin?: AdminClaims;
    }
  }
}

export function signAdminToken(claims: AdminClaims): string {
  return jwt.sign({ sub: claims.sub, email: claims.email }, env.JWT_SECRET, {
    expiresIn: '12h',
  });
}

export function requireAdmin(
  req: Request,
  res: Response,
  next: NextFunction,
): void {
  const header = req.header('authorization') ?? '';
  const match = /^Bearer\s+(.+)$/i.exec(header);
  if (!match) {
    res.status(401).json({ error: 'unauthorized' });
    return;
  }
  try {
    const payload = jwt.verify(match[1]!, env.JWT_SECRET) as jwt.JwtPayload;
    req.admin = { sub: String(payload.sub), email: String(payload.email) };
    next();
  } catch {
    res.status(401).json({ error: 'unauthorized' });
  }
}
