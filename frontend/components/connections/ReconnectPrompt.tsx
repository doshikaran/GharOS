import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/design-system/Button";
import { providerDisplayLabel, type OAuthProvider } from "@/lib/connections";
import styles from "./ReconnectPrompt.module.css";

/**
 * The reconnect prompt an auth failure surfaces as — a
 * `ConnectorFailure(is_auth_failure=true)` inside a run, or a
 * `409`/`428` precondition failure from `POST /ingest`, or a locally
 * revoked / expired credential in the connections list. Never a silent
 * empty scan, never a fabricated success (Gate 14.5, safety invariant 7).
 */
export interface ReconnectPromptProps {
  readonly provider: OAuthProvider | null;
  readonly principal: string | null;
  readonly reason: string;
  /** When provided together with a known `provider`, renders a direct
   * reconnect action; otherwise the prompt points the person at the
   * connection list. */
  readonly onReconnect?: (provider: OAuthProvider) => void;
}

export function ReconnectPrompt({ provider, principal, reason, onReconnect }: ReconnectPromptProps) {
  return (
    <div className={styles.prompt} role="alert" data-testid="reconnect-prompt">
      <AlertTriangle size={18} aria-hidden="true" className={styles.icon} />
      <div className={styles.body}>
        <p className={styles.title}>
          Reconnect needed{provider ? `: ${providerDisplayLabel(provider)}` : ""}
        </p>
        <p className={styles.reason}>{reason}</p>
        {principal && <p className={styles.principal}>Account: {principal}</p>}
        {provider && onReconnect ? (
          <Button variant="secondary" onClick={() => onReconnect(provider)}>
            Reconnect {providerDisplayLabel(provider)}
          </Button>
        ) : (
          <p className={styles.hint}>Reconnect this account from the connections list above, then run the scan again.</p>
        )}
      </div>
    </div>
  );
}
