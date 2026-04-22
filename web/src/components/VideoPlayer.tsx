import { forwardRef } from "react";

type VideoPlayerProps = {
  src: string;
  title: string;
};

/**
 * Thin wrapper around a native <video>.
 *
 * The backend serves `/job/<id>/analysis.mp4` with Range
 * support, so `preload="metadata"` is enough to let the browser
 * seek without downloading the full file up-front.
 *
 * `playsInline` keeps mobile Safari from forcing fullscreen on
 * play — the transcript workspace needs the player to stay in
 * the left rail so the active transcript row can scroll into
 * view beside it.
 */
const VideoPlayer = forwardRef<HTMLVideoElement, VideoPlayerProps>(
  function VideoPlayer({ src, title }, ref) {
    return (
      <section className="video-card" aria-label="Video player">
        <div className="video-shell">
          <video
            ref={ref}
            controls
            controlsList="nodownload"
            playsInline
            preload="metadata"
            src={src}
            title={title}
          />
        </div>
        <p className="video-caption" title={title}>
          {title}
        </p>
      </section>
    );
  },
);

export default VideoPlayer;
