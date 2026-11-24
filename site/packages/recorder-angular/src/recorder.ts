import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, computed, inject, signal } from "@angular/core";
import { HEIGHT, Player, WIDTH, across, browserClock, current, glyph, kindsIn, playLabel, readData, reading, rest, sentence, swing } from "@recorder/core";

@Component({
  selector: "recorder-angular-view",
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let now = reading();
    @let recording = view().recording;
    <section class="rec" [attr.aria-label]="recording.title">
      <div class="rec-choose" role="group" [attr.aria-label]="words.recordings">
        @for (choice of player.recordings; track choice.id) {
          <button type="button" [attr.aria-pressed]="choice.id === recording.id" (click)="player.choose(choice.id)">{{ choice.title }}</button>
        }
      </div>
      <p class="rec-about">
        <span class="rec-tag" [attr.data-real]="recording.real">{{ recording.real ? words.real : words.example }}</span>
        <span>{{ recording.about }}</span>
        @if (recording.url) {
          <a [href]="recording.url">{{ words.openRun }}</a>
        }
      </p>
      @if (recording.unseen) {
        <div class="rec-views" role="group" [attr.aria-label]="words.views">
          <button type="button" [attr.aria-pressed]="view().unseen" (click)="player.show(true)">{{ words.unseen }}</button>
          <button type="button" [attr.aria-pressed]="!view().unseen" (click)="player.show(false)">{{ words.seen }}</button>
        </div>
      }
      <div class="rec-sheet" [style.--at]="view().position">
        @for (lane of recording.lanes; track view().recording.id + lane.id) {
          <div class="rec-lane">
            <div class="rec-name">{{ lane.name }}</div>
            <svg class="rec-pen" [attr.viewBox]="paper" preserveAspectRatio="none" aria-hidden="true"
              (pointermove)="player.point(lane.id, across($event))" (pointerleave)="player.leave()" (click)="player.pick(lane.id, across($event))">
              <path class="rest" [attr.d]="rest(lane.id)" />
              @for (mark of view().marks; track $index) {
                @if (mark.lane === lane.id) {
                  <path [class]="'k-' + mark.kind" [class.now]="$index === current()" [attr.d]="swing(mark.kind, mark.at, recording.length)" />
                }
              }
            </svg>
          </div>
        }
        <div class="rec-needle"></div>
      </div>
      <p class="rec-readout" [attr.aria-live]="view().playing ? 'off' : 'polite'">
        <span class="at">{{ now ? now.time + ' ' + now.lane : '' }}</span>
        <span class="what" [class.said]="recording.real && now">{{ now ? now.what : words.start }}</span>
        @if (now) {
          <span class="result">
            <svg [attr.class]="'k-' + now.kind" [attr.viewBox]="stamp" aria-hidden="true"><path [attr.d]="glyph(now.kind)" /></svg>
            {{ now.result }}
          </span>
        }
      </p>
      <div class="rec-controls">
        <button type="button" class="play" (click)="player.toggle()">{{ playLabel() }}</button>
        <button type="button" class="step" [attr.aria-label]="words.back" (click)="player.step(-1)">‹</button>
        <button type="button" class="step" [attr.aria-label]="words.on" (click)="player.step(1)">›</button>
        <input #slider type="range" min="0" max="1000" [value]="sliderValue()" [attr.aria-label]="words.position"
          [attr.aria-valuetext]="sentence()" (input)="player.seek(slider.valueAsNumber / 1000)" />
      </div>
      <ul class="rec-legend" [attr.aria-label]="words.legend">
        @for (kind of kinds(); track kind) {
          <li>
            <svg [attr.class]="'k-' + kind" [attr.viewBox]="stamp" aria-hidden="true"><path [attr.d]="glyph(kind)" /></svg>
            {{ words.kinds[kind] }}
          </li>
        }
      </ul>
    </section>
  `,
})
export class Recorder {
  // The custom element that Angular makes is this component's own host element.
  private readonly data = readData(inject<ElementRef<HTMLElement>>(ElementRef).nativeElement);
  protected readonly words = this.data.words;
  protected readonly player = new Player(this.data.recordings, browserClock());
  protected readonly view = signal(this.player.view);
  protected readonly reading = computed(() => reading(this.view()));
  protected readonly current = computed(() => current(this.view()));
  protected readonly kinds = computed(() => kindsIn(this.view()));
  protected readonly playLabel = computed(() => playLabel(this.view(), this.words));
  protected readonly sentence = computed(() => sentence(this.view(), this.words));
  protected readonly sliderValue = computed(() => Math.round(this.view().position * 1000));
  protected readonly paper = `0 0 ${WIDTH} ${HEIGHT}`;
  protected readonly stamp = `0 0 24 ${HEIGHT}`;
  protected readonly across = across;
  protected readonly rest = rest;
  protected readonly swing = swing;
  protected readonly glyph = glyph;

  constructor() {
    const stop = this.player.subscribe(() => this.view.set(this.player.view));
    inject(DestroyRef).onDestroy(() => {
      stop();
      this.player.pause();
    });
  }
}
