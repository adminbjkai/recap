import { RefObject, useEffect, useState } from "react";
import type { TranscriptRow } from "../lib/format";

function findActiveIndex(rows: TranscriptRow[], currentTime: number): number {
  let lo = 0;
  let hi = rows.length - 1;
  let answer = -1;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (rows[mid].start <= currentTime) {
      answer = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return answer;
}

export function useActiveRow(
  videoRef: RefObject<HTMLVideoElement>,
  rows: TranscriptRow[],
): number | null {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const startsKey = rows.map((row) => row.start).join("|");

  useEffect(() => {
    const video = videoRef.current;
    if (!video || rows.length === 0) {
      setActiveIndex(null);
      return;
    }

    const update = () => {
      const index = findActiveIndex(rows, video.currentTime);
      setActiveIndex(index >= 0 ? index : null);
    };

    video.addEventListener("timeupdate", update);
    video.addEventListener("seeking", update);
    video.addEventListener("play", update);
    update();

    return () => {
      video.removeEventListener("timeupdate", update);
      video.removeEventListener("seeking", update);
      video.removeEventListener("play", update);
    };
  }, [videoRef, startsKey, rows]);

  return activeIndex;
}
