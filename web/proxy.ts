import { clerkMiddleware } from "@clerk/nextjs/server";

// The proxy only attaches the Clerk session. Each layout, route handler and server action checks
// auth itself (resource-based checks), so protection never depends on path matching.
export default clerkMiddleware();

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
