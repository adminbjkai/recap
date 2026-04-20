import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  uploadRecording,
  type RecordingUploadResponse,
} from "../lib/api";
import { formatElapsed, formatFileSize } from "../lib/format";

export type RecordingPanelProps = {
  onSaved: (response: RecordingUploadResponse) => void;
};

type Status =
  | "unsupported"
  | "idle"
  | "requesting"
  | "recording"
  | "stopped"
  | "saving"
  | "saved"
  | "error";

type MediaRecorderGlobal = typeof globalThis & {
  MediaRecorder?: {
    new (stream: MediaStream, options?: { mimeType?: string }): MediaRecorder;
    isTypeSupported?: (type: string) => boolean;
  };
};

function isRecordingSupported(): boolean {
  if (typeof window === "undefined") return false;
  const g = window as MediaRecorderGlobal;
  if (typeof g.MediaRecorder === "undefined") return false;
  if (typeof navigator === "undefined" || !navigator.mediaDevices) return false;
  if (typeof navigator.mediaDevices.getDisplayMedia !== "function") return false;
  return true;
}

function pickMimeType(): string | undefined {
  const g = window as MediaRecorderGlobal;
  const rec = g.MediaRecorder;
  if (!rec || typeof rec.isTypeSupported !== "function") return undefined;
  const candidates = [
    "video/webm;codecs=vp9,opus",
    "video/webm;codecs=vp8,opus",
    "video/webm",
    "video/mp4",
  ];
  for (const c of candidates) {
    try {
      if (rec.isTypeSupported(c)) return c;
    } catch (_err) {
      /* ignore */
    }
  }
  return undefined;
}

export default function RecordingPanel({ onSaved }: RecordingPanelProps) {
  const [status, setStatus] = useState<Status>(() =>
    isRecordingSupported() ? "idle" : "unsupported",
  );
  const [includeMic, setIncludeMic] = useState(true);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [saved, setSaved] = useState<RecordingUploadResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [micSkipped, setMicSkipped] = useState(false);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamsRef = useRef<MediaStream[]>([]);
  const chunksRef = useRef<Blob[]>([]);
  const blobRef = useRef<Blob | null>(null);
  const startedAtRef = useRef<number>(0);
  const tickerRef = useRef<number | null>(null);

  const stopAllStreams = useCallback(() => {
    for (const s of streamsRef.current) {
      try {
        s.getTracks().forEach((t) => t.stop());
      } catch (_err) {
        /* ignore */
      }
    }
    streamsRef.current = [];
    recorderRef.current = null;
  }, []);

  const clearTicker = useCallback(() => {
    if (tickerRef.current !== null) {
      window.clearInterval(tickerRef.current);
      tickerRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      stopAllStreams();
      clearTicker();
      if (previewUrl) {
        try {
          URL.revokeObjectURL(previewUrl);
        } catch (_err) {
          /* ignore */
        }
      }
    };
  }, [stopAllStreams, clearTicker, previewUrl]);

  const startRecording = useCallback(async () => {
    setErrorMessage(null);
    setMicSkipped(false);
    setStatus("requesting");
    try {
      const display = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: true,
      });
      streamsRef.current = [display];

      let composed: MediaStream = display;
      if (includeMic) {
        try {
          const mic = await navigator.mediaDevices.getUserMedia({
            audio: true,
          });
          streamsRef.current.push(mic);
          composed = new MediaStream();
          display.getVideoTracks().forEach((t) => composed.addTrack(t));
          display.getAudioTracks().forEach((t) => composed.addTrack(t));
          mic.getAudioTracks().forEach((t) => composed.addTrack(t));
        } catch (_err) {
          setMicSkipped(true);
        }
      }

      const mime = pickMimeType();
      const g = window as MediaRecorderGlobal;
      const Ctor = g.MediaRecorder;
      if (!Ctor) {
        throw new Error("MediaRecorder is not available.");
      }
      const recorder = new Ctor(
        composed,
        mime ? { mimeType: mime } : undefined,
      );
      chunksRef.current = [];
      recorder.ondataavailable = (e: BlobEvent) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onerror = () => {
        setErrorMessage("Browser reported a recording error.");
        setStatus("error");
        clearTicker();
        stopAllStreams();
      };
      recorder.onstop = () => {
        const blobType = mime || "video/webm";
        const blob = new Blob(chunksRef.current, {
          type: blobType.split(";")[0],
        });
        blobRef.current = blob;
        const url = URL.createObjectURL(blob);
        setPreviewUrl(url);
        setStatus("stopped");
        clearTicker();
        stopAllStreams();
      };
      // If the user stops the share via the browser picker itself,
      // the display video track ends — forward that to the recorder.
      const videoTrack = display.getVideoTracks()[0];
      if (videoTrack) {
        videoTrack.addEventListener("ended", () => {
          if (recorderRef.current && recorderRef.current.state === "recording") {
            try {
              recorderRef.current.stop();
            } catch (_err) {
              /* ignore */
            }
          }
        });
      }

      recorderRef.current = recorder;
      recorder.start(1000);
      startedAtRef.current = Date.now();
      setElapsedMs(0);
      clearTicker();
      tickerRef.current = window.setInterval(() => {
        setElapsedMs(Date.now() - startedAtRef.current);
      }, 250);
      setStatus("recording");
    } catch (err) {
      stopAllStreams();
      clearTicker();
      const msg =
        err instanceof Error
          ? err.message
          : "Could not start screen recording.";
      setErrorMessage(msg);
      setStatus("error");
    }
  }, [clearTicker, includeMic, stopAllStreams]);

  const stopRecording = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      try {
        recorder.stop();
      } catch (_err) {
        /* ignore */
      }
    }
  }, []);

  const discardRecording = useCallback(() => {
    if (previewUrl) {
      try {
        URL.revokeObjectURL(previewUrl);
      } catch (_err) {
        /* ignore */
      }
    }
    blobRef.current = null;
    setPreviewUrl(null);
    setStatus("idle");
    setElapsedMs(0);
    setErrorMessage(null);
    setMicSkipped(false);
  }, [previewUrl]);

  const saveRecording = useCallback(async () => {
    const blob = blobRef.current;
    if (!blob) return;
    setErrorMessage(null);
    setStatus("saving");
    const result = await uploadRecording(blob);
    if (result.kind === "saved") {
      setSaved(result.response);
      setStatus("saved");
      onSaved(result.response);
    } else {
      setErrorMessage(result.message);
      setStatus("error");
    }
  }, [onSaved]);

  const recordAgain = useCallback(() => {
    if (previewUrl) {
      try {
        URL.revokeObjectURL(previewUrl);
      } catch (_err) {
        /* ignore */
      }
    }
    blobRef.current = null;
    setPreviewUrl(null);
    setSaved(null);
    setStatus("idle");
    setElapsedMs(0);
    setErrorMessage(null);
    setMicSkipped(false);
  }, [previewUrl]);

  const blobSizeLabel = useMemo(() => {
    if (!previewUrl || !blobRef.current) return null;
    return formatFileSize(blobRef.current.size);
  }, [previewUrl]);

  if (status === "unsupported") {
    return (
      <div className="recording-panel">
        <div className="recording-unsupported" role="status">
          <strong>Your browser can't record screens here.</strong>
          <p>
            The Screen Capture + MediaRecorder APIs are missing. Try a
            recent Chrome, Edge, or Firefox — or pick an existing file
            from the Sources root or an absolute path.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="recording-panel">
      <p className="recording-privacy">
        Recordings stay local. Your browser captures the stream on this
        machine and uploads it straight into the server's sources root —
        nothing is sent to a third-party service.
      </p>

      {errorMessage ? (
        <p className="form-error" role="status">
          {errorMessage}
        </p>
      ) : null}

      {(status === "idle" || status === "error") && !previewUrl ? (
        <div className="recording-idle">
          <label className="recording-mic-toggle">
            <input
              type="checkbox"
              checked={includeMic}
              onChange={(e) => setIncludeMic(e.target.checked)}
              disabled={false}
            />
            <span>Include microphone audio</span>
          </label>
          <button
            type="button"
            className="primary-button"
            onClick={startRecording}
          >
            Start screen recording
          </button>
          <p className="recording-hint">
            You'll pick which screen, window, or tab to share in the
            browser's own prompt. Press <kbd>Stop</kbd> when you're done.
          </p>
        </div>
      ) : null}

      {status === "requesting" ? (
        <div className="recording-idle" aria-live="polite">
          <p>Waiting for the browser permission prompt…</p>
        </div>
      ) : null}

      {status === "recording" ? (
        <div className="recording-live" aria-live="polite">
          <div className="recording-indicator">
            <span className="recording-dot" aria-hidden="true" />
            <span>Recording · {formatElapsed(elapsedMs)}</span>
          </div>
          {micSkipped ? (
            <p className="recording-hint">
              Microphone was denied — continuing with display audio
              only.
            </p>
          ) : null}
          <button
            type="button"
            className="primary-button"
            onClick={stopRecording}
          >
            Stop recording
          </button>
        </div>
      ) : null}

      {status === "stopped" && previewUrl ? (
        <div className="recording-stopped">
          <video
            className="recording-preview"
            src={previewUrl}
            controls
            preload="metadata"
          />
          <p className="recording-meta">
            {formatElapsed(elapsedMs)} captured
            {blobSizeLabel ? ` · ${blobSizeLabel}` : ""}
          </p>
          <div className="recording-actions">
            <button
              type="button"
              className="primary-button"
              onClick={saveRecording}
            >
              Save to sources
            </button>
            <button
              type="button"
              className="ghost-button"
              onClick={discardRecording}
            >
              Discard &amp; record again
            </button>
          </div>
          <p className="recording-hint">
            Saving writes the clip into the sources root. Starting a
            recap is a separate, explicit step.
          </p>
        </div>
      ) : null}

      {status === "saving" ? (
        <div className="recording-idle" aria-live="polite">
          <p>Saving recording to sources…</p>
        </div>
      ) : null}

      {status === "saved" && saved ? (
        <div className="recording-saved">
          <p className="save-toast" role="status">
            Recording saved as <code>{saved.name}</code>
            {saved.size_bytes
              ? ` (${formatFileSize(saved.size_bytes)})`
              : ""}
            . It's selected in the Sources picker — click{" "}
            <strong>Start job</strong> when you're ready.
          </p>
          <button
            type="button"
            className="ghost-button"
            onClick={recordAgain}
          >
            Record another clip
          </button>
        </div>
      ) : null}
    </div>
  );
}
