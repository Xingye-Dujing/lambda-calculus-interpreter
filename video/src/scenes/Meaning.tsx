import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_LATIN, FONT_MONO, FONT_SERIF} from '../theme';
import {
  clamp,
  Kicker,
  Label,
  Reveal,
  Rule,
  SceneMeta,
  Stage,
} from '../components/core';

const Card: React.FC<{
  title: string;
  formula: string;
  delay: number;
  dark?: boolean;
}> = ({title, formula, delay}) => (
  <Reveal delay={delay} y={14} duration={20}>
    <div
      style={{
        width: 510,
        border: `1px solid ${C.border}`,
        background: C.paper,
        padding: '18px 20px',
      }}
    >
      <div
        style={{
          fontFamily: FONT_MONO,
          fontSize: 13,
          letterSpacing: '0.16em',
          color: C.faint,
        }}
      >
        {title}
      </div>
      <div
        style={{
          marginTop: 10,
          fontFamily: FONT_MONO,
          fontSize: 23,
          lineHeight: 1.55,
          whiteSpace: 'nowrap',
        }}
      >
        {formula}
      </div>
    </div>
  </Reveal>
);

const MergeDiagram: React.FC<{frame: number}> = ({frame}) => {
  const p1 = interpolate(frame, [210, 300], [0, 1], clamp);
  const p2 = interpolate(frame, [250, 340], [0, 1], clamp);
  const node = interpolate(frame, [330, 380], [0, 1], clamp);
  return (
    <svg
      viewBox="0 0 860 440"
      style={{position: 'absolute', left: 590, top: 380, width: 860, height: 440}}
    >
      <path
        d="M 10 92 C 130 92, 140 220, 250 220"
        fill="none"
        stroke={C.borderStrong}
        strokeWidth={1.2}
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - p1}
      />
      <path
        d="M 10 328 C 130 328, 140 220, 250 220"
        fill="none"
        stroke={C.borderStrong}
        strokeWidth={1.2}
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - p2}
      />
      <circle
        cx={264}
        cy={220}
        r={12}
        fill={node > 0.5 ? C.text : C.bg}
        stroke={C.text}
        strokeWidth={1.4}
        opacity={node}
      />
      <path
        d="M 278 220 L 370 220"
        fill="none"
        stroke={C.borderStrong}
        strokeWidth={1.2}
        opacity={node}
      />
      <text
        x={264}
        y={266}
        textAnchor="middle"
        fill={C.faint}
        fontFamily={FONT_MONO}
        fontSize={14}
        letterSpacing="0.1em"
        opacity={node}
      >
        SAME MEANING
      </text>
    </svg>
  );
};

export const Meaning: React.FC = () => {
  const frame = useCurrentFrame();
  const phaseA = interpolate(frame, [0, 30, 690, 750], [0, 1, 1, 0], clamp);
  const phaseB = interpolate(frame, [720, 790, 1420, 1480], [0, 1, 1, 0], clamp);
  const quote = interpolate(frame, [1060, 1130], [0, 1], clamp);

  return (
    <Stage>
      <SceneMeta chapter="SAME MEANING, DIFFERENT WRITINGS" index="06" />

      <div style={{opacity: phaseA}}>
        <div style={{position: 'absolute', left: 120, top: 160, width: 1100}}>
          <Kicker delay={8}>SAME MEANING   同义</Kicker>
          <div style={{height: 28}} />
          <div style={{fontFamily: FONT_SERIF, fontSize: 74, lineHeight: 1.36}}>
            同一个意思
            <br />
            <span style={{color: C.dim}}>可以有很多种写法</span>
          </div>
        </div>

        <div style={{position: 'absolute', left: 110, top: 446}}>
          <Card
            title="ADD₁"
            formula="λm.λn.λf.λx. m f (n f x)"
            delay={110}
          />
        </div>
        <div style={{position: 'absolute', left: 110, top: 682}}>
          <Card
            title="ADD₂"
            formula="λm.λn.λf.λx. n f (m f x)"
            delay={160}
          />
        </div>

        <MergeDiagram frame={frame} />

        <div style={{position: 'absolute', left: 960, top: 404, width: 760}}>
          <Reveal delay={340} y={10}>
            <Label color={C.faint}>TWO TESTS   两种比较</Label>
          </Reveal>
          <div style={{height: 18}} />
          <Reveal delay={380} y={16}>
            <div
              style={{
                borderTop: `1px solid ${C.borderStrong}`,
                borderBottom: `1px solid ${C.border}`,
                padding: '24px 0',
              }}
            >
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 120px',
                  rowGap: 18,
                  fontFamily: FONT_MONO,
                  fontSize: 22,
                  color: C.dim,
                  maxWidth: 620,
                }}
              >
                <span>:eq ADD₁ ADD₂</span>
                <span style={{color: C.err}}>false</span>
                <span>:conv ADD₁ ADD₂</span>
                <span style={{color: C.ok}}>true</span>
              </div>
            </div>
          </Reveal>
          <div style={{height: 24}} />
          <Reveal delay={500} y={12}>
            <div style={{fontFamily: FONT_SERIF, fontSize: 30, lineHeight: 1.6}}>
              同义
              <br />
              <span style={{color: C.dim}}>不等于同形</span>
            </div>
          </Reveal>
          <div style={{height: 22}} />
          <Reveal delay={600} y={10}>
            <div style={{fontFamily: FONT_SERIF, fontSize: 20, color: C.dim, lineHeight: 1.7}}>
              eq 比较的是写法
              <br />
              conv 比较的是归约之后
            </div>
          </Reveal>
        </div>
      </div>

      <div style={{opacity: phaseB}}>
        <div style={{position: 'absolute', left: 120, top: 160}}>
          <Kicker delay={750}>THE BOUNDARY   边界</Kicker>
          <div style={{height: 26}} />
          <div style={{fontFamily: FONT_SERIF, fontSize: 72, lineHeight: 1.36}}>
            同义 也有边界
          </div>
        </div>

        <div style={{position: 'absolute', left: 120, top: 340, width: 790}}>
          <Reveal delay={800} y={14}>
            <div style={{borderTop: `1px solid ${C.borderStrong}`, paddingTop: 20}}>
              <div style={{fontFamily: FONT_MONO, fontSize: 18, color: C.faint, letterSpacing: '0.08em'}}>
                MUL ADD ADD
              </div>
              <div style={{fontFamily: FONT_MONO, fontSize: 32, marginTop: 12}}>
                (mul add add a b c)′
              </div>
              <div style={{fontFamily: FONT_MONO, fontSize: 30, color: C.dim, marginTop: 6}}>
                = (c′^b′) × (a′+c′)
              </div>
            </div>
          </Reveal>
          <div style={{height: 38}} />
          <Reveal delay={900} y={14}>
            <div style={{borderTop: `1px solid ${C.border}`, paddingTop: 20}}>
              <div style={{fontFamily: FONT_MONO, fontSize: 18, color: C.faint, letterSpacing: '0.08em'}}>
                ADD MUL ADD
              </div>
              <div style={{fontFamily: FONT_MONO, fontSize: 32, marginTop: 12}}>
                (add mul add a b c)′
              </div>
              <div style={{fontFamily: FONT_MONO, fontSize: 30, color: C.dim, marginTop: 6}}>
                = c′^(a′×(a′+b′))
              </div>
            </div>
          </Reveal>
        </div>

        <div style={{position: 'absolute', left: 1030, top: 350, width: 750}}>
          <Reveal delay={980} y={12}>
            <div
              style={{
                border: `1px solid ${C.border}`,
                background: C.paper,
                padding: '24px 26px',
              }}
            >
              <Label color={C.faint}>A SMALL CORRECTION   一个小修正</Label>
              <div
                style={{
                  marginTop: 18,
                  fontFamily: FONT_SERIF,
                  fontSize: 28,
                  lineHeight: 1.65,
                }}
              >
                一个流行的说法是
                <br />
                mul add add 需要四个邱奇数
              </div>
              <div style={{height: 18}} />
              <div
                style={{
                  fontFamily: FONT_SERIF,
                  fontSize: 32,
                  color: C.text,
                  lineHeight: 1.6,
                }}
              >
                动手算一遍
                <br />
                三个就够了
              </div>
              <div style={{height: 20}} />
              <svg viewBox="0 0 300 60" style={{width: 300, height: 60}}>
                {[0, 1, 2].map((i) => (
                  <g key={i}>
                    <circle cx={40 + i * 78} cy={30} r={6} fill={C.text} />
                    <text
                      x={40 + i * 78}
                      y={54}
                      textAnchor="middle"
                      fill={C.faint}
                      fontFamily={FONT_MONO}
                      fontSize={12}
                    >
                      {i + 1}
                    </text>
                  </g>
                ))}
                <path
                  d="M 118 30 L 150 30"
                  stroke={C.borderStrong}
                  strokeWidth={1.2}
                />
                <path
                  d="M 196 30 L 228 30"
                  stroke={C.borderStrong}
                  strokeWidth={1.2}
                />
              </svg>
            </div>
          </Reveal>
        </div>

        <div
          style={{
            position: 'absolute',
            left: 120,
            bottom: 100,
            width: 900,
            opacity: quote,
          }}
        >
          <div
            style={{
              borderLeft: `2px solid ${C.borderStrong}`,
              paddingLeft: 26,
            }}
          >
            <div style={{fontFamily: FONT_SERIF, fontSize: 34, lineHeight: 1.6}}>
              同一含义
              <br />
              是一个很大的限制条件
            </div>
            <div
              style={{
                marginTop: 10,
                fontFamily: FONT_MONO,
                fontSize: 14,
                letterSpacing: '0.14em',
                color: C.faint,
              }}
            >
              FROM THE AUTHOR'S NOTES
            </div>
          </div>
        </div>

        <div
          style={{
            position: 'absolute',
            right: 120,
            bottom: 100,
            width: 690,
            textAlign: 'right',
            opacity: quote,
          }}
        >
          <div style={{fontFamily: FONT_SERIF, fontSize: 24, color: C.dim, lineHeight: 1.7}}>
            所以它把定义 环境 每一步都摊开
            <br />
            能复现 才能讨论
          </div>
        </div>
      </div>
    </Stage>
  );
};
