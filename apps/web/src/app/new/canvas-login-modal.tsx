"use client";

interface CanvasLoginModalProps {
  url: string;
  canvasLogging: boolean;
  canvasLoginError: string | null;
  onClose: () => void;
  onRetry: () => void;
  t: (key: string) => string;
}

export function CanvasLoginModal({
  url,
  canvasLogging,
  canvasLoginError,
  onClose,
  onRetry,
  t,
}: CanvasLoginModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-[420px] bg-card rounded-xl shadow-2xl p-6 flex flex-col gap-5 animate-in fade-in zoom-in-95 duration-200">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-foreground">
            {t("new.canvasLogin")}
          </h2>
          {!canvasLogging && (
            <button
              type="button"
              onClick={onClose}
              title={t("new.close")}
              className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground"
            >
              x
            </button>
          )}
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-muted-foreground">{t("new.canvasUrl")}</label>
          <div className="h-10 px-3 flex items-center border border-border rounded-lg bg-muted text-sm text-muted-foreground truncate">
            {url.trim()}
          </div>
        </div>

        {canvasLogging && (
          <div className="flex flex-col items-center gap-4 py-6">
            <div className="w-10 h-10 border-3 border-brand border-t-transparent rounded-full animate-spin" />
            <p className="text-sm font-medium text-foreground">
              {t("new.canvasBrowserOpened")}
            </p>
            <p className="text-[13px] text-muted-foreground text-center leading-relaxed">
              {t("new.canvasBrowserHelp")}
            </p>
          </div>
        )}

        {canvasLoginError && (
          <div className="p-3 bg-destructive/10 border border-destructive/30 rounded-md text-sm text-destructive">
            {canvasLoginError}
          </div>
        )}

        {!canvasLogging && canvasLoginError && (
          <div className="flex justify-end gap-3">
            <button
              type="button"
              data-testid="canvas-login-cancel"
              onClick={onClose}
              className="h-10 px-5 border border-border rounded-lg text-sm font-medium text-muted-foreground hover:border-foreground/20"
            >
              {t("new.cancel")}
            </button>
            <button
              type="button"
              data-testid="canvas-login-retry"
              onClick={onRetry}
              className="h-10 px-5 rounded-lg text-sm font-semibold text-brand-foreground bg-brand hover:opacity-90"
            >
              {t("new.retry")}
            </button>
          </div>
        )}

        <p className="text-[11px] text-muted-foreground leading-relaxed">
          {canvasLogging
            ? t("new.browserSessionNote")
            : t("new.loginTimeout")}
        </p>
      </div>
    </div>
  );
}
