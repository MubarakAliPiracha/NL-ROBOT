import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'NL-Robot',
  description: 'Natural-language robot simulation workspace',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        {children}
      </body>
    </html>
  );
}
