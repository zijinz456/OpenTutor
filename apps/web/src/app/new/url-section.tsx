"use client";

interface UrlSectionProps {
  url: string;
  onUrlChange: (value: string) => void;
  urlError: string | null;
  onValidateUrl: (value: string) => void;
  isCanvasDetected: boolean;
  canvasSessionValid: boolean;
  onAddUrl: () => void;
  t: (key: string) => string;
}

export function UrlSection({
  url,
  onUrlChange,
  urlError,
  onValidateUrl,
  isCanvasDetected,
  canvasSessionValid,
  onAddUrl,
  t,
}: UrlSectionProps) {
  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-base font-semibold text-foreground">{t("new.addUrl")}</h3>
      <div className="flex gap-2">
        <input
          data-testid="project-url-input"
          className={`flex-1 h-11 px-4 border rounded-lg bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand ${urlError ? "border-destructive" : "border-border"}`}
          placeholder={t("new.urlPlaceholder")}
          value={url}
          onChange={(e) => {
            onUrlChange(e.target.value);
            onValidateUrl(e.target.value);
          }}
          onBlur={() => onValidateUrl(url)}
        />
        <button
          type="button"
          data-testid="add-url-button"
          onClick={onAddUrl}
          className={`h-11 px-5 text-brand-foreground rounded-lg font-semibold text-sm ${
            isCanvasDetected && !canvasSessionValid
              ? "bg-warning hover:opacity-90"
              : "bg-brand hover:opacity-90"
          }`}
        >
          {isCanvasDetected && !canvasSessionValid ? t("new.loginAndAdd") : t("new.add")}
        </button>
      </div>
      {urlError && <p className="text-xs text-destructive mt-1">{urlError}</p>}
      {isCanvasDetected && !urlError && canvasSessionValid && (
        <div className="p-3 px-4 bg-success-muted border border-success/30 rounded-md text-sm text-success leading-relaxed">
          <span className="font-semibold">{t("new.canvasAuthedTitle")}</span>{" "}
          {t("new.canvasAuthedBody")}
        </div>
      )}
      {isCanvasDetected && !urlError && !canvasSessionValid && (
        <div className="p-3 px-4 bg-warning-muted border border-warning/30 rounded-md text-sm text-warning leading-relaxed">
          <span className="font-semibold">{t("new.canvasDetectedTitle")}</span>{" "}
          {t("new.canvasDetectedBody")}
        </div>
      )}
    </div>
  );
}

interface AutoScrapeSectionProps {
  autoScrape: boolean;
  onAutoScrapeChange: (value: boolean) => void;
  t: (key: string) => string;
}

export function AutoScrapeSection({ autoScrape, onAutoScrapeChange, t }: AutoScrapeSectionProps) {
  return (
    <div className="flex flex-col gap-4">
      <h3 className="text-base font-semibold text-foreground">{t("new.autoscrapeTitle")}</h3>
      <p className="text-[13px] text-muted-foreground">{t("new.autoscrapeDesc")}</p>
      <div className="flex items-center gap-3">
        <button
          type="button"
          data-testid="autoscrape-toggle"
          title={t("new.autoscrapeToggle")}
          aria-pressed={autoScrape}
          onClick={() => onAutoScrapeChange(!autoScrape)}
          className={`w-11 h-6 rounded-full relative transition-colors ${autoScrape ? "bg-brand" : "bg-muted-foreground/30"}`}
        >
          <div className={`w-[18px] h-[18px] bg-background rounded-full absolute top-[3px] transition-all ${autoScrape ? "right-[3px]" : "left-[3px]"}`} />
        </button>
        <span className="text-sm text-foreground">{t("new.autoscrapeToggle")}</span>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-sm text-muted-foreground">{t("new.frequency")}</span>
        <div className="flex items-center gap-2 px-3.5 h-10 border border-border rounded-md bg-background">
          <span className="text-[13px] text-foreground">{t("new.every24h")}</span>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <div className="w-[18px] h-[18px] rounded-[3px] bg-brand flex items-center justify-center shrink-0">
          <span className="text-[10px] text-brand-foreground font-bold">{"\u2713"}</span>
        </div>
        <span className="text-sm text-foreground">{t("new.remindExpiry")}</span>
      </div>
    </div>
  );
}
