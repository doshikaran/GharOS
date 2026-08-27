import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { RegisterImagePanel } from "./RegisterImagePanel";

const { fetchDocumentRawMock } = vi.hoisted(() => ({ fetchDocumentRawMock: vi.fn() }));

vi.mock("@/lib/graph-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/graph-api")>("@/lib/graph-api");
  return { ...actual, fetchDocumentRaw: fetchDocumentRawMock };
});

describe("RegisterImagePanel", () => {
  afterEach(() => {
    fetchDocumentRawMock.mockReset();
  });

  it("shows a loading state before the fetch resolves", () => {
    fetchDocumentRawMock.mockReturnValue(new Promise(() => {}));
    render(<RegisterImagePanel baseUrl="http://api.example" registerImageRef="doc-attendance-register" month="2026-08" />);
    expect(screen.getByRole("status")).toHaveTextContent(/Loading 2026-08's register photograph/);
  });

  it("renders the live register image when the fetch succeeds", async () => {
    fetchDocumentRawMock.mockResolvedValue({ contentType: "image/jpeg", bytes: new Uint8Array([1, 2, 3]) });
    render(<RegisterImagePanel baseUrl="http://api.example" registerImageRef="doc-attendance-register" month="2026-08" />);

    const image = await screen.findByRole("img", { name: /2026-08 handwritten attendance register/ });
    expect(image).toBeInTheDocument();
    expect(screen.getByText(/Live source document: doc-attendance-register/)).toBeInTheDocument();
  });

  it("falls back to a clearly-labelled static placeholder when the live fetch fails", async () => {
    fetchDocumentRawMock.mockRejectedValue(new Error("404 not found"));
    render(<RegisterImagePanel baseUrl="http://api.example" registerImageRef="doc-attendance-register-2026-07" month="2026-07" />);

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/Static placeholder/));
    expect(screen.getByRole("status")).toHaveTextContent(/not available right now/);
    expect(screen.getByRole("img", { name: /Static placeholder illustration/ })).toBeInTheDocument();
  });

  it("shows 'no register image on file' rather than fetching, when registerImageRef is null", () => {
    render(<RegisterImagePanel baseUrl="http://api.example" registerImageRef={null} month="2026-06" />);
    expect(screen.getByRole("status")).toHaveTextContent("No register image on file for 2026-06.");
    expect(fetchDocumentRawMock).not.toHaveBeenCalled();
  });

  it("never presents the static placeholder as if it were the real photograph", async () => {
    fetchDocumentRawMock.mockRejectedValue(new Error("network error"));
    render(<RegisterImagePanel baseUrl="http://api.example" registerImageRef="doc-missing" month="2026-05" />);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/Static placeholder/));
    expect(screen.queryByText(/Live source document/)).not.toBeInTheDocument();
  });
});
