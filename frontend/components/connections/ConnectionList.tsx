"use client";

import { CheckCircle2, Plug } from "lucide-react";
import { Badge } from "@/components/design-system/Badge";
import { Button } from "@/components/design-system/Button";
import { Card } from "@/components/design-system/Card";
import {
  OAUTH_PROVIDERS,
  oauthStartUrl,
  providerDisplayLabel,
  scopePlainLabel,
  type ConnectionRecord,
  type OAuthProvider,
} from "@/lib/connections";
import styles from "./ConnectionList.module.css";

export interface ConnectionListProps {
  readonly connections: readonly ConnectionRecord[];
  readonly baseUrl: string;
  readonly onDisconnect: (provider: OAuthProvider, principal: string) => void;
  /** `${provider}:${principal}` keys whose disconnect is in flight. */
  readonly disconnectingKeys: ReadonlySet<string>;
}

function formatDateTime(iso: string | null): string {
  if (!iso) return "never";
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? iso : parsed.toLocaleString();
}

function ProviderCard({
  provider,
  active,
  revoked,
  baseUrl,
  onDisconnect,
  disconnectingKeys,
}: {
  provider: OAuthProvider;
  active: ConnectionRecord | undefined;
  revoked: readonly ConnectionRecord[];
  baseUrl: string;
  onDisconnect: (provider: OAuthProvider, principal: string) => void;
  disconnectingKeys: ReadonlySet<string>;
}) {
  const label = providerDisplayLabel(provider);
  const key = active ? `${provider}:${active.principal}` : "";
  const disconnecting = key.length > 0 && disconnectingKeys.has(key);

  return (
    <Card className={styles.card}>
      <div className={styles.cardHead}>
        <h3 className={styles.provider}>{label}</h3>
        {active ? (
          <Badge variant="success" className={styles.statusBadge}>
            <CheckCircle2 size={14} aria-hidden="true" />
            Connected
          </Badge>
        ) : (
          <Badge variant="neutral">{revoked.length > 0 ? "Disconnected" : "Not connected"}</Badge>
        )}
      </div>

      {active ? (
        <>
          <dl className={styles.meta}>
            <div className={styles.metaRow}>
              <dt>Account</dt>
              <dd className={styles.mono}>{active.principal}</dd>
            </div>
            <div className={styles.metaRow}>
              <dt>Connected</dt>
              <dd>{formatDateTime(active.connected_at)}</dd>
            </div>
            <div className={styles.metaRow}>
              <dt>Last scan</dt>
              <dd>{formatDateTime(active.last_scan_at)}</dd>
            </div>
          </dl>

          <div className={styles.scopes}>
            <p className={styles.scopesLabel}>What you granted</p>
            <ul className={styles.scopeList}>
              {active.granted_scopes.map((scope) => (
                <li key={scope} className={styles.scopeItem}>
                  <span className={styles.scopePlain}>{scopePlainLabel(scope)}</span>
                  <span className={styles.scopeRaw}>{scope}</span>
                </li>
              ))}
            </ul>
          </div>

          <Button
            variant="secondary"
            onClick={() => onDisconnect(provider, active.principal)}
            disabled={disconnecting}
          >
            {disconnecting ? "Disconnecting…" : "Disconnect"}
          </Button>
        </>
      ) : (
        <>
          <p className={styles.blurb}>
            {provider === "google"
              ? "Read-only access to Gmail, plus per-file access to the Drive files you pick. Nothing is sent or changed."
              : "Read-only access to Outlook mail through Microsoft Graph. Nothing is sent or changed."}
          </p>
          {revoked.length > 0 && (
            <p className={styles.revokedNote}>
              Previously connected as <span className={styles.mono}>{revoked[0].principal}</span>, disconnected{" "}
              {formatDateTime(revoked[0].revoked_at)}.
            </p>
          )}
          <a className={styles.connectButton} href={oauthStartUrl(baseUrl, provider)}>
            <Plug size={16} aria-hidden="true" />
            Connect {label}
          </a>
        </>
      )}
    </Card>
  );
}

/**
 * The Gmail + Outlook connection state from `GET /connections`
 * (PHASES.md Phase 14.5, E4 brief). Status, last-scan time, and every
 * granted scope shown plainly. Connect is a full-page redirect to
 * `GET /oauth/{provider}/start` (an OAuth redirect, not a fetch);
 * disconnect posts to `POST /connections/{provider}/{principal}/disconnect`.
 */
export function ConnectionList({ connections, baseUrl, onDisconnect, disconnectingKeys }: ConnectionListProps) {
  return (
    <div className={styles.grid}>
      {OAUTH_PROVIDERS.map((provider) => {
        const forProvider = connections.filter((record) => record.provider === provider);
        const active = forProvider.find((record) => record.revoked_at === null);
        const revoked = forProvider
          .filter((record) => record.revoked_at !== null)
          .sort((a, b) => (b.revoked_at ?? "").localeCompare(a.revoked_at ?? ""));
        return (
          <ProviderCard
            key={provider}
            provider={provider}
            active={active}
            revoked={revoked}
            baseUrl={baseUrl}
            onDisconnect={onDisconnect}
            disconnectingKeys={disconnectingKeys}
          />
        );
      })}
    </div>
  );
}
