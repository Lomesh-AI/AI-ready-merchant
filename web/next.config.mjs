/** @type {import('next').NextConfig} */
const nextConfig = {
  // SSE through the /buyer-api rewrite MUST NOT be gzipped — compression buffers
  // the event stream and the browser sees nothing until the buffer fills.
  compress: false,
  async rewrites() {
    return [
      { source: "/merchant-api/:path*", destination: "http://merchant:8000/:path*" },
      { source: "/buyer-api/:path*", destination: "http://buyer:8001/:path*" },
    ];
  },
};
export default nextConfig;
