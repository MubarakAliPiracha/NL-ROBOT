import './globals.css';
import type { Metadata } from 'next';
import { ThemeProvider, themeInitScript } from '@/lib/theme';

export const metadata: Metadata = {
  title: 'NL-Robot',
  description: 'Natural-language robot simulation workspace',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
