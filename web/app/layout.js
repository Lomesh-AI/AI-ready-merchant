import "./globals.css";

export const metadata = { title: "Agentic Commerce MVP" };

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
      </head>
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
