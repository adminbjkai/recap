import { forwardRef } from "react";

type VideoPlayerProps = {
  src: string;
  title: string;
};

const VideoPlayer = forwardRef<HTMLVideoElement, VideoPlayerProps>(
  function VideoPlayer({ src, title }, ref) {
    return (
      <section className="video-card" aria-label="Video player">
        <div className="video-shell">
          <video
            ref={ref}
            controls
            preload="metadata"
            src={src}
            title={title}
          />
        </div>
      </section>
    );
  },
);

export default VideoPlayer;
