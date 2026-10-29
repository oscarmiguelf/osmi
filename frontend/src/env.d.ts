declare namespace App {
  interface Locals {
    /** Set by the middleware on every page that requires a signed-in user. */
    session?: import('./lib/api').Session;
    /** Valid access token for calling the API on the user's behalf (server only). */
    accessToken?: string;
    /** Branch the user is working in (their only one, or the one picked after signing in). */
    branch?: import('./lib/api').Session['branches'][number];
    /** The visitor's real IP (lib/clientIp.ts), set on every request. */
    clientIp?: string;
  }
}
