import React from 'react';
import {
  AbsoluteFill,
  Audio,
  interpolate,
  Sequence,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import {C, FPS} from './theme';
import {Footage, type Caption, type Profile} from './components/Footage';
import {ChapterCard} from './components/ChapterCard';
import {FontFaces} from './components/ui';

type CardSegment = {
  kind: 'card';
  seconds: number;
  no: string;
  kicker: string;
  title: string;
  formula?: string;
  body?: string;
};

type ClipSegment = {
  kind: 'clip';
  scene: string;
  seconds: number;
  no: string;
  chapter: string;
  caption: Caption[];
};

type Segment = CardSegment | ClipSegment;

// 字幕只保留中文，公式与代码保留原样 / Chinese-only captions, formulas untouched
const BILI_SEGMENTS: Segment[] = [
  {
    kind: 'card',
    seconds: 7,
    no: '00',
    kicker: 'λ · LAMBDA CALCULUS',
    title: '一条规则\n写出整个世界',
    body: '一场可以看见过程的计算',
  },
  {
    kind: 'clip',
    scene: 'intro',
    seconds: 6.9,
    no: '01',
    chapter: 'THE INSTRUMENT  ·  仪器',
    caption: [
      {zh: '先看最小的一步'},
      {zh: 'id = \\x.x'},
    ],
  },
  {
    kind: 'clip',
    scene: 'trace',
    seconds: 6.9,
    no: '02',
    chapter: 'TRACE  ·  轨迹',
    caption: [
      {zh: '结果之外 还有过程'},
      {zh: '每一步都有前后对照'},
    ],
  },
  {
    kind: 'clip',
    scene: 'manual',
    seconds: 6.8,
    no: '03',
    chapter: 'MANUAL  ·  手动',
    caption: [
      {zh: '同一个项 路径由你决定'},
      {zh: '先归约根 还是先归约参数'},
    ],
  },
  {
    kind: 'card',
    seconds: 12,
    no: '01',
    kicker: 'ONE RULE  ·  一条规则',
    title: '一条规则\n反复使用',
    formula: '(λx. M) N  →  M[x := N]',
    body: '变量 · 抽象 · 应用',
  },
  {
    kind: 'clip',
    scene: 'ast',
    seconds: 4.9,
    no: '04',
    chapter: 'STRUCTURE  ·  结构',
    caption: [
      {zh: '结构视图'},
      {zh: '语法树 · de Bruijn'},
    ],
  },
  {
    kind: 'clip',
    scene: 'type',
    seconds: 4.5,
    no: '05',
    chapter: 'TYPE  ·  类型',
    caption: [
      {zh: '类型不是装饰'},
      {zh: '从项本身推出 支持 let 泛化'},
    ],
  },
  {
    kind: 'clip',
    scene: 'env',
    seconds: 5.7,
    no: '06',
    chapter: 'ENVIRONMENT  ·  环境',
    caption: [
      {zh: '定义先展开 再保存'},
      {zh: '后来的重定义不改过去'},
    ],
  },
  {
    kind: 'clip',
    scene: 'race',
    seconds: 5.5,
    no: '07',
    chapter: 'STRATEGY RACE  ·  竞速',
    caption: [
      {zh: '四种策略 四条路'},
      {zh: '换一条路 看到的就不一样'},
    ],
  },
  {
    kind: 'clip',
    scene: 'fast',
    seconds: 5.8,
    no: '08',
    chapter: 'FAST MODE  ·  快速',
    caption: [
      {zh: '大数交给快速模式'},
      {zh: '省下的时间留给结果'},
    ],
  },
  {
    kind: 'card',
    seconds: 13,
    no: '02',
    kicker: 'THE PATH  ·  路',
    title: '最简式只有一个\n路不止一条',
    body: '应用序会掉进 Ω  正规序一步到 y',
  },
  {
    kind: 'clip',
    scene: 'guide',
    seconds: 5,
    no: '09',
    chapter: 'GUIDE  ·  指引',
    caption: [
      {zh: '三步开始'},
      {zh: 'git clone · ./build.sh · ./extension'},
    ],
  },
  {
    kind: 'card',
    seconds: 11,
    no: '03',
    kicker: 'λ',
    title: '把答案怎么出现\n交给你看',
    body: 'github.com/Xingye-Dujing/lambda-calculus-interpreter',
  },
];

const DOUYIN_SEGMENTS: Segment[] = [
  {
    kind: 'card',
    seconds: 5,
    no: 'λ',
    kicker: 'LAMBDA CALCULUS',
    title: '一条规则\n写出整个世界',
    body: '可以看见过程的计算',
  },
  {
    kind: 'clip',
    scene: 'intro',
    seconds: 6,
    no: '01',
    chapter: 'THE INSTRUMENT',
    caption: [
      {zh: '一行定义 一次归约'},
      {zh: 'id = \\x.x'},
    ],
  },
  {
    kind: 'clip',
    scene: 'trace',
    seconds: 5.8,
    no: '02',
    chapter: 'TRACE',
    caption: [
      {zh: '结果之外 还有过程'},
      {zh: '每一步都可以停下来看'},
    ],
  },
  {
    kind: 'card',
    seconds: 8,
    no: '01',
    kicker: 'ONE RULE',
    title: '把参数\n放进它该在的位置',
    formula: '(λx. M) N → M[x := N]',
  },
  {
    kind: 'clip',
    scene: 'ast',
    seconds: 2.9,
    no: '03',
    chapter: 'STRUCTURE',
    caption: [{zh: '一个项的骨架'}],
  },
  {
    kind: 'clip',
    scene: 'type',
    seconds: 2.5,
    no: '04',
    chapter: 'TYPE',
    caption: [{zh: '类型 是另一种结构'}],
  },
  {
    kind: 'clip',
    scene: 'race',
    seconds: 3.4,
    no: '05',
    chapter: 'STRATEGY RACE',
    caption: [
      {zh: '四种策略 四条路'},
      {zh: '同一项 不同中间形态'},
    ],
  },
  {
    kind: 'card',
    seconds: 7,
    no: '02',
    kicker: 'THE PATH',
    title: '最简式只有一个\n路不止一条',
    body: '应用序掉进 Ω  正规序一步到 y',
  },
  {
    kind: 'clip',
    scene: 'guide',
    seconds: 2.2,
    no: '06',
    chapter: 'GET STARTED',
    caption: [{zh: '三步开始'}],
  },
  {
    kind: 'card',
    seconds: 9,
    no: 'λ',
    kicker: 'LAMBDA CALCULUS',
    title: '如果它也让你\n多看了一眼计算',
    body: '欢迎 star\ngithub.com/Xingye-Dujing/lambda-calculus-interpreter',
  },
];

const PaperCut: React.FC<{cuts: number[]}> = ({cuts}) => {
  const frame = useCurrentFrame();
  let opacity = 0;
  for (const cut of cuts) {
    const d = frame - cut;
    if (d >= -5 && d <= 6) {
      opacity = Math.max(opacity, 1 - Math.abs(d) / 6);
    }
  }
  return (
    <AbsoluteFill
      style={{background: C.bg, opacity: opacity * 0.7, pointerEvents: 'none'}}
    />
  );
};

const ProgressRail: React.FC<{total: number; cuts: number[]}> = ({total, cuts}) => {
  const frame = useCurrentFrame();
  const p = Math.max(0, Math.min(1, frame / total));
  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        height: 3,
        background: 'rgba(20,21,24,0.10)',
        zIndex: 20,
      }}
    >
      <div style={{width: `${p * 100}%`, height: '100%', background: C.dim}} />
      {cuts.map((cut, i) => (
        <div
          key={i}
          style={{
            position: 'absolute',
            left: `${(cut / total) * 100}%`,
            top: 0,
            width: 1,
            height: 7,
            background: 'rgba(20,21,24,0.22)',
          }}
        />
      ))}
    </div>
  );
};

export const FootageFilm: React.FC<{profile: Profile; segments: Segment[]}> = ({
  profile,
  segments,
}) => {
  const lengths = segments.map((s) => Math.round(s.seconds * FPS));
  const starts: number[] = [];
  let acc = 0;
  for (const len of lengths) {
    starts.push(acc);
    acc += len;
  }
  const total = acc;
  const cuts = starts.slice(1);

  return (
    <AbsoluteFill style={{background: C.bg}}>
      <FontFaces />
      <Audio src={staticFile('audio/ambient.wav')} loop volume={0.16} />

      {segments.map((segment, i) => (
        <Sequence key={i} from={starts[i]} durationInFrames={lengths[i]}>
          {segment.kind === 'card' ? (
            <ChapterCard profile={profile} {...segment} />
          ) : (
            <Footage
              profile={profile}
              scene={segment.scene}
              no={segment.no}
              chapter={segment.chapter}
              caption={segment.caption}
            />
          )}
        </Sequence>
      ))}

      <PaperCut cuts={cuts} />
      <ProgressRail total={total} cuts={cuts} />
    </AbsoluteFill>
  );
};

export const BiliPromo: React.FC = () => (
  <FootageFilm profile="bili" segments={BILI_SEGMENTS} />
);

export const DouyinPromo: React.FC = () => (
  <FootageFilm profile="douyin" segments={DOUYIN_SEGMENTS} />
);

export const BILI_FRAMES = Math.round(
  BILI_SEGMENTS.reduce((a, s) => a + s.seconds, 0) * FPS,
);
export const DOUYIN_FRAMES = Math.round(
  DOUYIN_SEGMENTS.reduce((a, s) => a + s.seconds, 0) * FPS,
);
