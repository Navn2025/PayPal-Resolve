import type { NextConfig } from "next";

const config: NextConfig = {
  poweredByHeader: false,
  devIndicators: false,
  logging: {
    incomingRequests: { ignore: [/^\/api\/customer-account\/google\/callback/, /^\/api\/auth\/paypal\/callback/] },
  },
  distDir: process.env.RESOLVE_UI_TEST_SERVER === "1" ? ".next-test" : process.env.RESOLVE_UI_PREVIEW === "1" ? ".next-preview" : ".next",
  turbopack: { root: process.cwd() },
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "X-Frame-Options", value: "DENY" },
      ],
    }, {
      source: "/customer/:path*",
      headers: [
        { key: "Referrer-Policy", value: "no-referrer" },
        { key: "X-Robots-Tag", value: "noindex, nofollow" },
      ],
    }];
  },
};

export default config;
