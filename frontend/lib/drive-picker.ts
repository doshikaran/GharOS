/**
 * Google Picker loader for the Phase 14.5 Drive-picker ingestion path
 * (PHASES.md Phase 14.5, E4 brief — "a Google Picker (`drive.file` scope)
 * for choosing specific Drive files ... if CSP/loading is a problem,
 * degrade gracefully").
 *
 * Architecture note (ADR-022): GharOS is backend-only for OAuth — the
 * browser never holds a long-lived token. The Picker widget, however, is
 * a browser component that needs a short-lived `drive.file` access token
 * and a Google API key. So this module:
 *
 *   1. loads Google's own loader (`https://apis.google.com/js/api.js` —
 *      an allowed Google origin) and the `picker` module, and
 *   2. is handed a short-lived access token by the caller, which the
 *      caller obtains from E3's `GET /oauth/google/picker-token` endpoint
 *      (minted from the stored Google refresh token for a connected
 *      principal — see this file's `PickerTokenResponse`).
 *
 * If the loader is blocked (CSP), or the API key / app id env vars are
 * unset, or the token endpoint is absent, the caller renders a documented
 * degraded state instead — the Picker is an enhancement, not a
 * requirement for the drag-and-drop upload path.
 */

/** `NEXT_PUBLIC_GOOGLE_PICKER_API_KEY` — a browser API key (not a
 * secret) for the Picker widget. Unset in local dev by default. */
export const GOOGLE_PICKER_API_KEY = process.env.NEXT_PUBLIC_GOOGLE_PICKER_API_KEY ?? "";

/** `NEXT_PUBLIC_GOOGLE_APP_ID` — the Google Cloud project number, shown
 * by the Picker as the requesting app. */
export const GOOGLE_APP_ID = process.env.NEXT_PUBLIC_GOOGLE_APP_ID ?? "";

/** True when the browser-side config the Picker needs is present. When
 * false, the Drive button renders its degraded state. */
export function isDrivePickerConfigured(): boolean {
  return GOOGLE_PICKER_API_KEY.length > 0 && GOOGLE_APP_ID.length > 0;
}

/** Shape of `GET /oauth/google/picker-token?principal=<p>` (E3, ADR-022
 * follow-up — see the report's integration-points section). A short-lived
 * `drive.file` access token for the Picker widget only; never persisted
 * client-side beyond the open Picker. */
export interface PickerTokenResponse {
  readonly access_token: string;
  readonly expires_in: number;
}

/** One file the user picked, narrowed from the Picker's response doc. */
export interface PickedDriveFile {
  readonly id: string;
  readonly name: string;
  readonly mimeType: string;
}

const LOADER_SRC = "https://apis.google.com/js/api.js";
const LOADER_TIMEOUT_MS = 10_000;

interface GapiLike {
  load(module: "picker", callback: () => void): void;
}

interface PickerViewLike {
  setMimeTypes(mimeTypes: string): PickerViewLike;
}

interface PickerBuilderLike {
  addView(view: unknown): PickerBuilderLike;
  setOAuthToken(token: string): PickerBuilderLike;
  setDeveloperKey(key: string): PickerBuilderLike;
  setAppId(appId: string): PickerBuilderLike;
  setCallback(cb: (data: Record<string, unknown>) => void): PickerBuilderLike;
  setTitle(title: string): PickerBuilderLike;
  build(): { setVisible(visible: boolean): void };
}

interface GooglePickerNamespace {
  readonly picker: {
    readonly DocsView: new (viewId?: unknown) => PickerViewLike;
    readonly ViewId: { readonly DOCS: unknown; readonly PDFS: unknown };
    readonly PickerBuilder: new () => PickerBuilderLike;
    readonly Action: { readonly PICKED: string; readonly CANCEL: string };
    readonly Response: { readonly ACTION: string; readonly DOCUMENTS: string };
    readonly Document: { readonly ID: string; readonly NAME: string; readonly MIME_TYPE: string };
  };
}

type PickerWindow = Window & {
  gapi?: GapiLike;
  google?: GooglePickerNamespace;
};

let loaderPromise: Promise<void> | null = null;

/** Injects Google's loader once, then loads the `picker` module.
 * Rejects on a load error (CSP block) or timeout. */
export function loadGooglePicker(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("The Google Picker is only available in the browser."));
  }
  if (loaderPromise) return loaderPromise;

  loaderPromise = new Promise<void>((resolve, reject) => {
    const win = window as PickerWindow;

    const loadPickerModule = () => {
      if (!win.gapi) {
        reject(new Error("Google's API loader did not initialise."));
        return;
      }
      win.gapi.load("picker", () => {
        if (win.google?.picker) resolve();
        else reject(new Error("The Google Picker module failed to load."));
      });
    };

    if (win.gapi) {
      loadPickerModule();
      return;
    }

    const existing = document.querySelector<HTMLScriptElement>(`script[src="${LOADER_SRC}"]`);
    const script = existing ?? document.createElement("script");
    const timeoutId = window.setTimeout(() => {
      reject(new Error("Loading the Google Picker timed out (it may be blocked by the page's content policy)."));
    }, LOADER_TIMEOUT_MS);

    script.addEventListener("load", () => {
      window.clearTimeout(timeoutId);
      loadPickerModule();
    });
    script.addEventListener("error", () => {
      window.clearTimeout(timeoutId);
      loaderPromise = null;
      reject(new Error("The Google Picker script could not be loaded (blocked or offline)."));
    });

    if (!existing) {
      script.src = LOADER_SRC;
      script.async = true;
      document.head.appendChild(script);
    }
  });

  return loaderPromise;
}

export interface OpenDrivePickerArgs {
  readonly oauthToken: string;
  readonly apiKey: string;
  readonly appId: string;
  readonly onPicked: (files: readonly PickedDriveFile[]) => void;
  readonly onCancel?: () => void;
}

/**
 * Opens the Google Picker restricted to Docs and PDFs. Assumes
 * `loadGooglePicker()` has already resolved.
 */
export function openDrivePicker(args: OpenDrivePickerArgs): void {
  const win = window as PickerWindow;
  const picker = win.google?.picker;
  if (!picker) throw new Error("The Google Picker is not loaded.");

  const docsView = new picker.DocsView(picker.ViewId.DOCS).setMimeTypes(
    "application/pdf,image/png,image/jpeg,image/heic,image/webp",
  );

  const built = new picker.PickerBuilder()
    .addView(docsView)
    .setOAuthToken(args.oauthToken)
    .setDeveloperKey(args.apiKey)
    .setAppId(args.appId)
    .setTitle("Choose files to bring into GharOS")
    .setCallback((data: Record<string, unknown>) => {
      const action = data[picker.Response.ACTION];
      if (action === picker.Action.CANCEL) {
        args.onCancel?.();
        return;
      }
      if (action !== picker.Action.PICKED) return;
      const rawDocs = data[picker.Response.DOCUMENTS];
      const docs = Array.isArray(rawDocs) ? rawDocs : [];
      const files: PickedDriveFile[] = [];
      for (const doc of docs) {
        if (typeof doc !== "object" || doc === null) continue;
        const record = doc as Record<string, unknown>;
        const id = record[picker.Document.ID];
        const name = record[picker.Document.NAME];
        const mimeType = record[picker.Document.MIME_TYPE];
        if (typeof id === "string") {
          files.push({
            id,
            name: typeof name === "string" ? name : id,
            mimeType: typeof mimeType === "string" ? mimeType : "application/octet-stream",
          });
        }
      }
      if (files.length > 0) args.onPicked(files);
    })
    .build();

  built.setVisible(true);
}

/** `GET /oauth/google/picker-token?principal=<principal>` (E3). */
export async function fetchPickerToken(
  baseUrl: string,
  principal: string,
): Promise<PickerTokenResponse> {
  const url = `${baseUrl}/oauth/google/picker-token?principal=${encodeURIComponent(principal)}`;
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`Could not get a Drive access token (HTTP ${response.status}).`);
  }
  const raw: unknown = await response.json();
  if (
    typeof raw === "object" &&
    raw !== null &&
    typeof (raw as Record<string, unknown>).access_token === "string"
  ) {
    const record = raw as Record<string, unknown>;
    return {
      access_token: record.access_token as string,
      expires_in: typeof record.expires_in === "number" ? record.expires_in : 3600,
    };
  }
  throw new Error("The Drive access-token response was not in the expected shape.");
}
