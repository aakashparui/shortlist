/** @type {import('next').NextConfig} */
const nextConfig = {
  // pdfjs loads its worker via a runtime dynamic import. Bundling it breaks
  // that resolution ("Cannot find module pdf.worker.mjs"), so leave it to be
  // required from node_modules on the server instead.
  serverExternalPackages: ["pdfjs-dist"],
  webpack: (config) => {
    config.resolve.extensionAlias = {
      ".js": [".ts", ".tsx", ".js"],
    };
    return config;
  },
};

export default nextConfig;
