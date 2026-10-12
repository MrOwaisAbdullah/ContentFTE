import { ArticlesTabs } from "./tabs";

// Articles section (spec §5): Content / Keywords / Research / Briefs as
// sub-tabs under one top-nav entry — the sheet workbook grouped together.
export default function ArticlesLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="space-y-6">
      <ArticlesTabs />
      {children}
    </div>
  );
}
