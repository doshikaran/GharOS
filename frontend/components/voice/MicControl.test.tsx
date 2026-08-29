import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MicControl } from "./MicControl";

describe("MicControl", () => {
  it("push-to-talk mode: mousedown starts, mouseup stops", () => {
    const onStart = vi.fn();
    const onStop = vi.fn();
    render(
      <MicControl
        listening={false}
        permission="granted"
        continuousMode={false}
        onContinuousModeChange={vi.fn()}
        onStart={onStart}
        onStop={onStop}
      />,
    );
    const button = screen.getByRole("button", { name: /Hold to talk/ });
    fireEvent.mouseDown(button);
    expect(onStart).toHaveBeenCalledOnce();
    fireEvent.mouseUp(button);
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("push-to-talk mode: leaving the button while pressed stops listening (no stuck-open mic)", () => {
    const onStop = vi.fn();
    render(
      <MicControl
        listening={true}
        permission="granted"
        continuousMode={false}
        onContinuousModeChange={vi.fn()}
        onStart={vi.fn()}
        onStop={onStop}
      />,
    );
    fireEvent.mouseLeave(screen.getByRole("button"));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("push-to-talk mode: keyboard Space starts on keydown and stops on keyup, without repeat re-triggering start", () => {
    const onStart = vi.fn();
    const onStop = vi.fn();
    render(
      <MicControl
        listening={false}
        permission="granted"
        continuousMode={false}
        onContinuousModeChange={vi.fn()}
        onStart={onStart}
        onStop={onStop}
      />,
    );
    const button = screen.getByRole("button");
    fireEvent.keyDown(button, { key: " " });
    fireEvent.keyDown(button, { key: " ", repeat: true });
    expect(onStart).toHaveBeenCalledOnce();
    fireEvent.keyUp(button, { key: " " });
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("continuous mode: click toggles listening on and off rather than press/hold", () => {
    const onStart = vi.fn();
    const onStop = vi.fn();
    const { rerender } = render(
      <MicControl
        listening={false}
        permission="granted"
        continuousMode={true}
        onContinuousModeChange={vi.fn()}
        onStart={onStart}
        onStop={onStop}
      />,
    );
    const button = screen.getByRole("button", { name: /Start hands-free/ });
    fireEvent.mouseDown(button);
    fireEvent.mouseUp(button);
    expect(onStart).not.toHaveBeenCalled();
    fireEvent.click(button);
    expect(onStart).toHaveBeenCalledOnce();

    rerender(
      <MicControl
        listening={true}
        permission="granted"
        continuousMode={true}
        onContinuousModeChange={vi.fn()}
        onStart={onStart}
        onStop={onStop}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Stop hands-free/ }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("disables the button and announces guidance, never a raw error, when permission is denied", () => {
    render(
      <MicControl
        listening={false}
        permission="denied"
        continuousMode={false}
        onContinuousModeChange={vi.fn()}
        onStart={vi.fn()}
        onStop={vi.fn()}
      />,
    );
    expect(screen.getByRole("button")).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(/Microphone access was denied/);
  });

  it("the hands-free toggle calls onContinuousModeChange and is disabled mid-listen", () => {
    const onContinuousModeChange = vi.fn();
    render(
      <MicControl
        listening={false}
        permission="granted"
        continuousMode={false}
        onContinuousModeChange={onContinuousModeChange}
        onStart={vi.fn()}
        onStop={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("switch", { name: /Hands-free/ }));
    expect(onContinuousModeChange).toHaveBeenCalledWith(true);
  });
});
