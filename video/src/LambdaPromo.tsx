import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Sequence,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import {C, FPS} from './theme';
import {FontFaces} from './components/ui';
import {ColdOpen} from './scenes/ColdOpen';
import {OneRule} from './scenes/OneRule';
import {Church} from './scenes/Church';
import {Positioning} from './scenes/Positioning';
import {Demo} from './scenes/Demo';
import {Paths} from './scenes/Paths';
import {Meaning} from './scenes/Meaning';
import {Usage} from './scenes/Usage';
import {Ending} from './scenes/Ending';

const durations = {
  cold: 22 * FPS,
  rule: 44 * FPS,
  church: 50 * FPS,
  positioning: 32 * FPS,
  demo: 68 * FPS,
  paths: 52 * FPS,
  meaning: 52 * FPS,
  usage: 38 * FPS,
  ending: 24 * FPS,
};

export const TOTAL_FRAMES = Object.values(durations).reduce((a, b) => a + b, 0);

const starts = {
  cold: 0,
  rule: durations.cold,
  church: durations.cold + durations.rule,
  positioning: durations.cold + durations.rule + durations.church,
  demo: durations.cold + durations.rule + durations.church + durations.positioning,
  paths:
    durations.cold +
    durations.rule +
    durations.church +
    durations.positioning +
    durations.demo,
  meaning:
    durations.cold +
    durations.rule +
    durations.church +
    durations.positioning +
    durations.demo +
    durations.paths,
  usage:
    durations.cold +
    durations.rule +
    durations.church +
    durations.positioning +
    durations.demo +
    durations.paths +
    durations.meaning,
  ending:
    durations.cold +
    durations.rule +
    durations.church +
    durations.positioning +
    durations.demo +
    durations.paths +
    durations.meaning +
    durations.usage,
};

const cuts = [
  starts.rule,
  starts.church,
  starts.positioning,
  starts.demo,
  starts.paths,
  starts.meaning,
  starts.usage,
  starts.ending,
];

const PaperCut: React.FC = () => {
  const frame = useCurrentFrame();
  let opacity = 0;
  for (const cut of cuts) {
    const d = frame - cut;
    if (d >= -7 && d <= 8) {
      opacity = Math.max(opacity, 1 - Math.abs(d) / 8);
    }
  }
  return (
    <AbsoluteFill
      style={{
        background: C.bg,
        opacity: opacity * 0.72,
        pointerEvents: 'none',
      }}
    />
  );
};

const ProgressRail: React.FC = () => {
  const frame = useCurrentFrame();
  const p = Math.max(0, Math.min(1, frame / TOTAL_FRAMES));
  const dark = frame >= starts.paths && frame < starts.meaning;
  const base = dark ? 'rgba(255,255,255,0.16)' : 'rgba(20,21,24,0.10)';
  const fill = dark ? 'rgba(255,255,255,0.48)' : 'rgba(20,21,24,0.34)';
  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        height: 2,
        background: base,
        zIndex: 20,
      }}
    >
      <div style={{width: `${p * 100}%`, height: '100%', background: fill}} />
      {cuts.map((cut, i) => (
        <div
          key={i}
          style={{
            position: 'absolute',
            left: `${(cut / TOTAL_FRAMES) * 100}%`,
            top: 0,
            width: 1,
            height: 6,
            background: dark ? 'rgba(255,255,255,0.28)' : 'rgba(20,21,24,0.20)',
          }}
        />
      ))}
    </div>
  );
};

export const LambdaPromo: React.FC = () => {
  return (
    <AbsoluteFill style={{background: C.bg}}>
      <FontFaces />
      <Audio src={staticFile('audio/ambient.wav')} loop volume={0.16} />

      <Sequence from={starts.cold} durationInFrames={durations.cold}>
        <ColdOpen />
      </Sequence>
      <Sequence from={starts.rule} durationInFrames={durations.rule}>
        <OneRule />
      </Sequence>
      <Sequence from={starts.church} durationInFrames={durations.church}>
        <Church />
      </Sequence>
      <Sequence from={starts.positioning} durationInFrames={durations.positioning}>
        <Positioning />
      </Sequence>
      <Sequence from={starts.demo} durationInFrames={durations.demo}>
        <Demo />
      </Sequence>
      <Sequence from={starts.paths} durationInFrames={durations.paths}>
        <Paths />
      </Sequence>
      <Sequence from={starts.meaning} durationInFrames={durations.meaning}>
        <Meaning />
      </Sequence>
      <Sequence from={starts.usage} durationInFrames={durations.usage}>
        <Usage />
      </Sequence>
      <Sequence from={starts.ending} durationInFrames={durations.ending}>
        <Ending />
      </Sequence>

      <PaperCut />
      <ProgressRail />
    </AbsoluteFill>
  );
};
