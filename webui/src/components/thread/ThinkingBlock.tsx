import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

interface ThinkingBlockProps {
  variant?: "card" | "inline";
}

/**
 * DeepSeek-style "thinking" indicator shown while the model is reasoning
 * before producing the first token, or while the assistant message is
 * still empty during streaming.
 *
 * "card" — standalone block rendered at thread level when no assistant
 *          streaming message exists yet.
 * "inline" — compact version rendered inside the assistant bubble when
 *            the message exists but has no content yet.
 */
export function ThinkingBlock({ variant = "card" }: ThinkingBlockProps) {
  const { t } = useTranslation();
  const label = t("message.thinking");

  if (variant === "inline") {
    return (
      <span
        aria-label={label}
        className="inline-flex items-center gap-1 py-1"
      >
        <ShimmerText>{label}</ShimmerText>
      </span>
    );
  }

  return (
    <div
      aria-label={label}
      className={cn(
        "w-full animate-in fade-in-0 slide-in-from-bottom-2 duration-300",
      )}
    >
      <div
        className={cn(
          "flex items-center gap-3 px-4 py-3",
        )}
      >
        <PulseDot />
        <span className="flex items-center gap-1 text-[14px] font-medium">
          <ShimmerText>{label}</ShimmerText>
        </span>
      </div>
    </div>
  );
}

/** A single dot that pulses with a soft glow. */
function PulseDot() {
  return (
    <span className="relative flex h-2.5 w-2.5">
      <span
        className={cn(
          "absolute inline-flex h-full w-full rounded-full",
          "bg-primary/60 animate-ping",
        )}
        style={{ animationDuration: "1.8s" }}
      />
      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-primary/70" />
    </span>
  );
}

/** Text with a shimmer gradient that sweeps across. */
function ShimmerText({ children }: { children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "bg-gradient-to-r from-muted-foreground/55 via-muted-foreground to-muted-foreground/55",
        "bg-[length:200%_100%] bg-clip-text text-transparent",
        "animate-shimmer",
      )}
      style={{
        animationDuration: "2.2s",
        animationTimingFunction: "ease-in-out",
        animationIterationCount: "infinite",
      }}
    >
      {children}
    </span>
  );
}

