import { NextResponse, type NextRequest } from "next/server";

/**
 * Edge middleware that gates dashboard/project routes behind a presence check for the
 * refresh-token cookie set by the client after login. The actual authentication is
 * enforced by the backend API (which validates the bearer token on every request); this
 * is only a fast client-side redirect so unauthenticated users land on the login page
 * instead of seeing a brief flash of a 401 state. It does not validate the token.
 */

const PROTECTED_PREFIXES = ["/dashboard", "/projects"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const isProtected = PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
  if (!isProtected) {
    return NextResponse.next();
  }

  const hasSession = request.cookies.has("aw_refresh");
  if (!hasSession) {
    const loginUrl = new URL("/auth/login", request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/projects/:path*"],
};
