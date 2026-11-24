import { useState, useSyncExternalStore, type CSSProperties } from "react";
import { HEIGHT, Player, WIDTH, across, browserClock, current, glyph, kindsIn, playLabel, reading, rest, sentence, swing, type Data } from "@recorder/core";

export function Recorder({ words, recordings }: Data) {
  const [player] = useState(() => new Player(recordings, browserClock()));
  const view = useSyncExternalStore(player.subscribe, () => player.view);
  const { recording, marks, position } = view;
  const now = reading(view);

  return (
    <section className="rec" aria-label={recording.title}>
      <div className="rec-choose" role="group" aria-label={words.recordings}>
        {recordings.map(({ id, title }) => (
          <button key={id} type="button" aria-pressed={id === recording.id} onClick={() => player.choose(id)}>
            {title}
          </button>
        ))}
      </div>
      <p className="rec-about">
        <span className="rec-tag" data-real={recording.real}>{recording.real ? words.real : words.example}</span>
        <span>{recording.about}</span>
        {recording.url && <a href={recording.url}>{words.openRun}</a>}
      </p>
      {recording.unseen && (
        <div className="rec-views" role="group" aria-label={words.views}>
          <button type="button" aria-pressed={view.unseen} onClick={() => player.show(true)}>{words.unseen}</button>
          <button type="button" aria-pressed={!view.unseen} onClick={() => player.show(false)}>{words.seen}</button>
        </div>
      )}
      <div className="rec-sheet" style={{ "--at": position } as CSSProperties}>
        {recording.lanes.map((lane) => (
          <div key={`${recording.id} ${lane.id}`} className="rec-lane">
            <div className="rec-name">{lane.name}</div>
            <svg
              className="rec-pen" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" aria-hidden="true"
              onPointerMove={(event) => player.point(lane.id, across(event))} onPointerLeave={() => player.leave()} onClick={(event) => player.pick(lane.id, across(event))}
            >
              <path className="rest" d={rest(lane.id)} />
              {marks.map((mark, i) =>
                mark.lane === lane.id ? (
                  <path key={i} className={`k-${mark.kind}${i === current(view) ? " now" : ""}`} d={swing(mark.kind, mark.at, recording.length)} />
                ) : null,
              )}
            </svg>
          </div>
        ))}
        <div className="rec-needle" />
      </div>
      <p className="rec-readout" aria-live={view.playing ? "off" : "polite"}>
        <span className="at">{now && `${now.time} ${now.lane}`}</span>
        <span className={`what${recording.real && now ? " said" : ""}`}>{now ? now.what : words.start}</span>
        {now && (
          <span className="result">
            <svg className={`k-${now.kind}`} viewBox={`0 0 24 ${HEIGHT}`} aria-hidden="true"><path d={glyph(now.kind)} /></svg>
            {now.result}
          </span>
        )}
      </p>
      <div className="rec-controls">
        <button type="button" className="play" onClick={() => player.toggle()}>{playLabel(view, words)}</button>
        <button type="button" className="step" aria-label={words.back} onClick={() => player.step(-1)}>‹</button>
        <button type="button" className="step" aria-label={words.on} onClick={() => player.step(1)}>›</button>
        <input
          type="range" min={0} max={1000} value={Math.round(position * 1000)} aria-label={words.position}
          aria-valuetext={sentence(view, words)} onChange={(event) => player.seek(event.target.valueAsNumber / 1000)}
        />
      </div>
      <ul className="rec-legend" aria-label={words.legend}>
        {kindsIn(view).map((kind) => (
          <li key={kind}>
            <svg className={`k-${kind}`} viewBox={`0 0 24 ${HEIGHT}`} aria-hidden="true"><path d={glyph(kind)} /></svg>
            {words.kinds[kind]}
          </li>
        ))}
      </ul>
    </section>
  );
}
