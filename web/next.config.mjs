/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      { source: "/merchant-api/:path*", destination: "http://merchant:8000/:path*" },
      { source: "/buyer-api/:path*", destination: "http://buyer:8001/:path*" },
    ];
  },
};
export default nextConfig;
