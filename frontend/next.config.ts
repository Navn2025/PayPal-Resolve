import type { NextConfig } from "next";

const config: NextConfig = {
  poweredByHeader: false,
  devIndicators: false,
  distDir: process.env.RESOLVE_UI_TEST_SERVER === "1" ? ".next-test" : ".next",
  turbopack: { root: process.cwd() },
  async headers() {
    return [{
      source: "/customer/:path*",
      headers: [
        { key: "Referrer-Policy", value: "no-referrer" },
        { key: "X-Robots-Tag", value: "noindex, nofollow" },
      ],
    }];
  },
};

export default config;
