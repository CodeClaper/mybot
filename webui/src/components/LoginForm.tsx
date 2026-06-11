import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface LoginFormProps {
  failed?: boolean;
  onLogin: (username: string, password: string) => void;
}

export function LoginForm({ failed, onLogin }: LoginFormProps) {
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const u = username.trim();
    const p = password.trim();
    if (!u || !p) return;
    setSubmitting(true);
    onLogin(u, p);
  };

  return (
    <div className="flex h-full w-full items-center justify-center px-6">
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-sm flex-col gap-4"
      >
        <div className="flex flex-col items-center gap-1 text-center">
          <p className="text-lg font-semibold">{t("app.login.title")}</p>
          <p className="text-sm text-muted-foreground">{t("app.login.hint")}</p>
        </div>
        {failed && (
          <p className="text-center text-sm text-destructive">
            {t("app.login.invalid")}
          </p>
        )}
        <Input
          type="text"
          placeholder={t("app.login.usernamePlaceholder")}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          disabled={submitting}
          autoFocus
          autoComplete="username"
        />
        <Input
          type="password"
          placeholder={t("app.login.passwordPlaceholder")}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={submitting}
          autoComplete="current-password"
        />
        <Button
          type="submit"
          className="w-full"
          disabled={!username.trim() || !password.trim() || submitting}
        >
          {t("app.login.submit")}
        </Button>
      </form>
    </div>
  );
}
