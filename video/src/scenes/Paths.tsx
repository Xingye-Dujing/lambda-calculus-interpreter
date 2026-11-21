import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_LATIN, FONT_MONO, FONT_SERIF} from '../theme';
import {
  clamp,
  Kicker,
  Label,
  Reveal,
  SceneMeta,
  Stage,
} from '../components/core';

const draw = (frame: number, start: number, duration: number) =>
  interpolate(frame, [start, start + duration], [0, 1], {
    ...clamp,
    easing: (t) => 1 - Math.pow(1 - t, 3),
  });

const Node: React.FC<{
  x: number;
  y: number;
  label: string;
  dark?: boolean;
  filled?: boolean;
  delay?: number;
}> = ({x, y, label, dark = true, filled = false, delay = 0}) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [delay, delay + 22], [0, 1], clamp);
  return (
    <g opacity={p}>
      <circle
        cx={x}
        cy={y}
        r={7}
        fill={filled ? (dark ? C.darkText : C.text) : dark ? C.dark : C.bg}
        stroke={dark ? C.darkText : C.text}
        strokeWidth={1.4}
      />
      <text
        x={x + 16}
        y={y + 5}
        fill={dark ? C.darkText : C.text}
        fontFamily={FONT_MONO}
        fontSize={17}
        letterSpacing="0.02em"
      >
        {label}
      </text>
    </g>
  );
};

const PathDiagram: React.FC<{frame: number}> = ({frame}) => {
  const upper = draw(frame, 260, 70);
  const lower = draw(frame, 430, 60);
  const loop = draw(frame, 560, 55);
  const upperText = interpolate(frame, [720, 780], [0, 1], clamp);
  const lowerText = interpolate(frame, [760, 820], [0, 1], clamp);
  return (
    <svg viewBox="0 0 1680 430" style={{width: 1680, height: 430}}>
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill={C.darkFaint} />
        </marker>
      </defs>
      <Node x={110} y={215} label="(λx.y) (Ω)" delay={200} filled />
      <path
        d="M 120 205 C 280 205, 300 92, 470 92"
        fill="none"
        stroke={C.darkFaint}
        strokeWidth={1.4}
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - upper}
      />
      <path
        d="M 120 225 C 280 225, 300 338, 470 338"
        fill="none"
        stroke={C.darkFaint}
        strokeWidth={1.4}
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - lower}
      />
      <path
        d="M 470 92 C 540 92, 540 35, 610 35 C 680 35, 680 150, 610 150 C 540 150, 540 92, 610 92"
        fill="none"
        stroke={C.darkErr}
        strokeWidth={1.6}
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - loop}
      />
      <path
        d="M 700 92 L 880 92"
        fill="none"
        stroke={C.darkErr}
        strokeWidth={1.6}
        markerEnd="url(#arrow)"
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - upper}
      />
      <path
        d="M 470 338 L 880 338"
        fill="none"
        stroke={C.darkOk}
        strokeWidth={1.8}
        markerEnd="url(#arrow)"
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - lower}
      />
      <g opacity={upperText}>
        <text x={300} y={62} fill={C.darkFaint} fontFamily={FONT_MONO} fontSize={15} letterSpacing="0.12em">
          APPLICATIVE  应用序
        </text>
        <text x={610} y={78} fill={C.darkFaint} fontFamily={FONT_MONO} fontSize={15}>
          Ω → Ω → Ω → …
        </text>
        <text x={930} y={98} fill={C.darkErr} fontFamily={FONT_MONO} fontSize={18}>
          不终止  diverges
        </text>
      </g>
      <g opacity={lowerText}>
        <text x={300} y={378} fill={C.darkFaint} fontFamily={FONT_MONO} fontSize={15} letterSpacing="0.12em">
          NORMAL ORDER  正规序
        </text>
        <text x={930} y={344} fill={C.darkOk} fontFamily={FONT_MONO} fontSize={20}>
          y
        </text>
        <text x={930} y={370} fill={C.darkFaint} fontFamily={FONT_MONO} fontSize={15}>
          1 步  1 step
        </text>
      </g>
    </svg>
  );
};

export const Paths: React.FC = () => {
  const frame = useCurrentFrame();
  const phaseB = interpolate(frame, [900, 980], [0, 1], clamp);
  const phaseC = interpolate(frame, [1220, 1300], [0, 1], clamp);
  const titleOpacity = interpolate(frame, [0, 25], [0, 1], clamp);

  return (
    <Stage dark>
      <SceneMeta chapter="THE ROAD MATTERS" index="05" dark right="NORMAL ORDER   Ω" />

      <div style={{opacity: titleOpacity, position: 'absolute', left: 120, top: 160}}>
        <Kicker dark delay={10}>CONFLUENCE & STRATEGY   合流与策略</Kicker>
        <div style={{height: 28}} />
        <div style={{fontFamily: FONT_SERIF, fontSize: 76, lineHeight: 1.34}}>
          最简式只有一个
          <br />
          <span style={{color: C.darkDim}}>但到达它的路 不止一条</span>
        </div>
      </div>

      <div style={{position: 'absolute', left: 120, top: 430}}>
        <PathDiagram frame={frame} />
      </div>

      <div
        style={{
          position: 'absolute',
          left: 120,
          right: 120,
          bottom: 94,
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 60,
        }}
      >
        <div style={{maxWidth: 780}}>
          <Reveal delay={880} y={12}>
            <div
              style={{
                fontFamily: FONT_SERIF,
                fontSize: 38,
                lineHeight: 1.5,
              }}
            >
              应用序 先算参数 会掉进 Ω
              <br />
              正规序 先丢参数 一步就到 y
            </div>
          </Reveal>
          <div style={{height: 18}} />
          <Reveal delay={1020} y={10} style={{opacity: phaseB}}>
            <div style={{fontFamily: FONT_SERIF, fontSize: 24, color: C.darkDim}}>
              策略不是口味问题
              <span style={{color: C.darkText}}> 是你会不会到达答案</span>
            </div>
          </Reveal>
        </div>

        <div style={{width: 660, opacity: phaseC}}>
          <Reveal delay={1280} y={14}>
            <div
              style={{
                borderTop: `1px solid ${C.darkBorderStrong}`,
                paddingTop: 20,
              }}
            >
              <div style={{fontFamily: FONT_SERIF, fontSize: 36, lineHeight: 1.45}}>
                是否存在正规形
                <br />
                <span style={{color: C.darkWarn}}>这件事本身不可判定</span>
              </div>
              <div style={{height: 16}} />
              <div
                style={{
                  fontFamily: FONT_MONO,
                  fontSize: 18,
                  lineHeight: 1.7,
                  color: C.darkDim,
                  border: `1px solid ${C.darkBorder}`,
                  padding: '12px 14px',
                }}
              >
                ⚠ 已达到 10000 步上限，归约未完成
                <br />
                <span style={{color: C.darkFaint}}>
                  step limit reached, reduction incomplete
                </span>
              </div>
              <div style={{height: 16}} />
              <div style={{fontFamily: FONT_SERIF, fontSize: 24, color: C.darkDim}}>
                所以 步数上限不是保守
                <span style={{color: C.darkText}}> 是诚实</span>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </Stage>
  );
};
