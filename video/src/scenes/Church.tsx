import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_LATIN, FONT_MONO, FONT_SERIF} from '../theme';
import {
  clamp,
  CodeLine,
  Kicker,
  Label,
  Panel,
  Reveal,
  SceneMeta,
  Stage,
  Typewriter,
} from '../components/core';

const Dot: React.FC<{i: number; frame: number; start: number}> = ({i, frame, start}) => {
  const p = interpolate(frame, [start + i * 55, start + i * 55 + 20], [0, 1], clamp);
  return (
    <g opacity={p}>
      <circle
        cx={50 + i * 135}
        cy={58 - Math.sin((i / 4) * Math.PI) * 26}
        r={6}
        fill={p > 0 ? C.text : 'transparent'}
        stroke={C.text}
        strokeWidth={1.3}
      />
      <text
        x={50 + i * 135}
        y={30 - Math.sin((i / 4) * Math.PI) * 26}
        textAnchor="middle"
        fill={C.dim}
        fontFamily={FONT_MONO}
        fontSize={15}
      >
        f
      </text>
    </g>
  );
};

const ChurchCurve: React.FC<{frame: number; start: number}> = ({frame, start}) => {
  const path = interpolate(frame, [start, start + 70], [0, 1], {
    ...clamp,
    easing: (t) => 1 - Math.pow(1 - t, 3),
  });
  return (
    <svg viewBox="0 0 620 90" style={{width: '100%', height: 96, overflow: 'visible'}}>
      <path
        d="M 20 68 C 150 18, 470 18, 600 68"
        fill="none"
        stroke={C.borderStrong}
        strokeWidth={1.2}
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - path}
      />
      {[0, 1, 2, 3, 4].map((i) => (
        <Dot key={i} i={i} frame={frame} start={start + 20} />
      ))}
      <text
        x={600}
        y={86}
        fill={C.faint}
        fontFamily={FONT_MONO}
        fontSize={15}
        textAnchor="middle"
      >
        x
      </text>
    </svg>
  );
};

export const Church: React.FC = () => {
  const frame = useCurrentFrame();
  const endFade = interpolate(frame, [1270, 1340], [0, 1], clamp);
  const bodyFade = interpolate(frame, [1230, 1300], [1, 0], clamp);

  return (
    <Stage>
      <SceneMeta chapter="NUMBERS AS ACTIONS" index="02" />

      <div style={{opacity: bodyFade}}>
        <div style={{position: 'absolute', left: 120, top: 180, width: 760}}>
          <Kicker delay={8}>CHURCH NUMERALS   邱奇数</Kicker>
          <div style={{height: 34}} />
          <Reveal delay={24} y={24}>
            <div style={{fontFamily: FONT_SERIF, fontSize: 82, lineHeight: 1.34}}>
              数字不是名词
              <br />
              是动作重复的次数
            </div>
          </Reveal>
          <div style={{height: 46}} />
          <Reveal delay={120} y={12}>
            <div
              style={{
                borderTop: `1px solid ${C.borderStrong}`,
                borderBottom: `1px solid ${C.border}`,
                padding: '22px 0',
                fontFamily: FONT_MONO,
                fontSize: 38,
                lineHeight: 1.7,
              }}
            >
              n = λf. λx. fⁿ(x)
            </div>
          </Reveal>
          <div style={{height: 16}} />
          <Reveal delay={170} y={10}>
            <div style={{fontFamily: FONT_SERIF, fontSize: 23, color: C.dim}}>
              把 f 重复 n 次 再作用到 x 上
              <br />
              数 是再做一次的节奏
            </div>
          </Reveal>

          <div style={{height: 54}} />
          <Reveal delay={250} y={12}>
            <div
              style={{
                display: 'flex',
                gap: 54,
                fontFamily: FONT_MONO,
                fontSize: 22,
                color: C.dim,
                lineHeight: 1.9,
              }}
            >
              <div>
                <span style={{color: C.faint}}>TWO</span>
                <br />
                λf.λx. f (f x)
              </div>
              <div>
                <span style={{color: C.faint}}>THREE</span>
                <br />
                λf.λx. f (f (f x))
              </div>
            </div>
          </Reveal>
        </div>

        <div style={{position: 'absolute', left: 1010, top: 208}}>
          <Panel padding={0} style={{width: 790, height: 590, background: C.paper}}>
            <div
              style={{
                height: 54,
                borderBottom: `1px solid ${C.border}`,
                display: 'flex',
                alignItems: 'center',
                padding: '0 22px',
                fontFamily: FONT_MONO,
                fontSize: 15,
                letterSpacing: '0.12em',
                color: C.dim,
              }}
            >
              LAMBDA-REPL
              <span style={{flex: 1}} />
              <span style={{color: C.faint}}>applicative   10000 steps</span>
            </div>
            <div style={{padding: '28px 30px'}}>
              <CodeLine size={25} color={C.text}>
                <span style={{color: C.faint}}>λ&gt; </span>
                <Typewriter text="PLUS TWO THREE" delay={420} speed={1.2} />
              </CodeLine>
              <div style={{height: 18}} />
              <Reveal delay={610} y={10}>
                <CodeLine size={27} color={C.text}>
                  <span style={{color: C.faint}}>⇒ </span>
                  λf → λx → f (f (f (f (f x))))
                </CodeLine>
              </Reveal>
              <div style={{height: 10}} />
              <Reveal delay={680} y={8}>
                <div
                  style={{
                    fontFamily: FONT_MONO,
                    fontSize: 17,
                    color: C.faint,
                    paddingLeft: 34,
                  }}
                >
                  6 步  6 steps    邱奇数 5  Church numeral 5
                </div>
              </Reveal>
              <div style={{height: 44}} />
              <Reveal delay={760} y={10}>
                <Label color={C.faint}>FIVE REPETITIONS   五次重复</Label>
              </Reveal>
              <div
                style={{
                  marginTop: 22,
                  display: 'flex',
                  alignItems: 'center',
                  padding: '0 10px',
                }}
              >
                <ChurchCurve frame={frame} start={820} />
              </div>
              <div style={{height: 30}} />
              <Reveal delay={1090} y={10}>
                <div
                  style={{
                    fontFamily: FONT_SERIF,
                    fontSize: 24,
                    color: C.dim,
                    lineHeight: 1.7,
                  }}
                >
                  5 不是一个符号
                  <br />
                  是再做一次 重复了五次
                </div>
              </Reveal>
            </div>
          </Panel>
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          inset: 0,
          opacity: endFade,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <div style={{textAlign: 'center'}}>
          <div
            style={{
              fontFamily: FONT_SERIF,
              fontSize: 78,
              lineHeight: 1.4,
            }}
          >
            过程没有被藏起来
            <br />
            每一步都留在屏幕上
          </div>
          <div style={{height: 34}} />
          <div
            style={{
              fontFamily: FONT_MONO,
              fontSize: 24,
              letterSpacing: '0.14em',
              color: C.faint,
            }}
          >
            (λx. M) N → M[x := N]
          </div>
        </div>
      </div>
    </Stage>
  );
};
