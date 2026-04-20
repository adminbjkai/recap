type Props = {
  query: string;
  onQueryChange: (value: string) => void;
  matchCount: number;
  activeMatchIndex: number | null;
  onPrev: () => void;
  onNext: () => void;
};

export default function TranscriptSearchBar({
  query,
  onQueryChange,
  matchCount,
  activeMatchIndex,
  onPrev,
  onNext,
}: Props) {
  const trimmed = query.trim();
  const hasMatch = matchCount > 0;
  const countClass = !trimmed
    ? ""
    : hasMatch
    ? "has-match"
    : "no-match";

  const countLabel = !trimmed
    ? ""
    : hasMatch
    ? `${(activeMatchIndex ?? 0) + 1} / ${matchCount}`
    : "0 matches";

  return (
    <div className="transcript-search" role="search">
      <label className="transcript-search-input">
        <span className="visually-hidden">Search transcript</span>
        <input
          type="search"
          placeholder="Search transcript"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          autoComplete="off"
          spellCheck={false}
          onKeyDown={(e) => {
            if (!hasMatch) return;
            if (e.key === "Enter") {
              e.preventDefault();
              if (e.shiftKey) {
                onPrev();
              } else {
                onNext();
              }
            }
          }}
        />
        {query ? (
          <button
            type="button"
            className="transcript-search-clear"
            aria-label="Clear search"
            onClick={() => onQueryChange("")}
          >
            ×
          </button>
        ) : null}
      </label>
      <span
        className={`transcript-search-count ${countClass}`}
        aria-live="polite"
      >
        {countLabel}
      </span>
      <div className="transcript-search-nav" aria-label="Cycle matches">
        <button
          type="button"
          aria-label="Previous match"
          disabled={!hasMatch}
          onClick={onPrev}
        >
          ↑
        </button>
        <button
          type="button"
          aria-label="Next match"
          disabled={!hasMatch}
          onClick={onNext}
        >
          ↓
        </button>
      </div>
    </div>
  );
}
