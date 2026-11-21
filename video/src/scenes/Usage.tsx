import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {C, FONT_LATIN, FONT_MONO, FONT_SERIF} from '../theme';
import {
  clamp,
  Kicker,
  Label,
  Panel,
  Reveal,
  SceneMeta,
  Stage,
  Typewriter,
} from '../components/core';
import {CommandChip} from '../components/ui';

const CodePanel: React.FC<{
  label: string;
  sub: string;
  lines: string[];
  delay: number;
  x: number;
}> = ({label, sub, lines, delay, x}) => (
  <div style={{position: 'absolute', left: x, top: 432, width: 800}}>
    <Reveal delay={delay} y={16}>
      <Panel padding={0} style={{width: 800}}>
        <div
          style={{
            height: 48,
            borderBottom: `1px solid ${C.border}`,
            display: 'flex',
            alignItems: 'center',
            padding: '0 20px',
            fontFamily: FONT_MONO,
            fontSize: 14,
            letterSpacing: '0.12em',
            color: C.dim,
          }}
        >
          {label}
          <span style={{flex: 1}} />
          <span style={{color: C.faint}}>{sub}</span>
        </div>
        <div style={{padding: '22px 24px', minHeight: 230}}>
          {lines.map((line, i) => (
            <div
              key={line}
              style={{
                fontFamily: FONT_MONO,
                fontSize: i === 0 ? 16 : 18,
                lineHeight: 1.9,
                color: line.startsWith('#') ? C.faint : C.text,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {i === 0 ? (
                <Typewriter text={line} delay={delay + 40} speed={1.6} />
              ) : (
                <Reveal delay={delay + 90 + i * 50} y={5} duration={12}>
                  {line}
                </Reveal>
              )}
            </div>
          ))}
        </div>
      </Panel>
    </Reveal>
  </div>
);

const FlowDiagram: React.FC<{frame: number}> = ({frame}) => {
  const p = interpolate(frame, [720, 850], [0, 1], clamp);
  const nodes = [
    ['extension.hs', 'GHC'],
    ['extension', 'CLI'],
    ['web/app.py', 'Flask'],
    ['browser', 'UI'],
  ];
  return (
    <svg viewBox="0 0 1680 100" style={{width: 1680, height: 100}}>
      {nodes.map(([a, b], i) => {
        const x = 30 + i * 410;
        return (
          <g key={a} opacity={interpolate(frame, [760 + i * 60, 800 + i * 60], [0, 1], clamp)}>
            {i < nodes.length - 1 ? (
              <path
                d={`M ${x + 250} 50 L ${x + 360} 50`}
                stroke={C.borderStrong}
                strokeWidth={1}
                strokeDasharray={1}
                pathLength={1}
                strokeDashoffset={1 - p}
              />
            ) : null}
            <rect
              x={x}
              y={20}
              width={250}
              height={60}
              fill="transparent"
              stroke={C.border}
              strokeWidth={1}
            />
            <text
              x={x + 16}
              y={45}
              fill={C.text}
              fontFamily={FONT_MONO}
              fontSize={17}
            >
              {a}
            </text>
            <text
              x={x + 16}
              y={66}
              fill={C.faint}
              fontFamily={FONT_MONO}
              fontSize={12}
              letterSpacing="0.1em"
            >
              {b}
            </text>
          </g>
        );
      })}
    </svg>
  );
};

export const Usage: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <Stage>
      <SceneMeta chapter="GET STARTED" index="07" />

      <div style={{position: 'absolute', left: 120, top: 160}}>
        <Kicker delay={6}>USAGE   使用</Kicker>
        <div style={{height: 26}} />
        <div style={{fontFamily: FONT_SERIF, fontSize: 74, lineHeight: 1.35}}>
          想自己试试
          <br />
          <span style={{color: C.dim}}>其实只要几步</span>
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          right: 120,
          top: 190,
          textAlign: 'right',
          fontFamily: FONT_LATIN,
          fontSize: 20,
          lineHeight: 1.7,
          color: C.faint,
        }}
      >
        Haskell + Flask
        <br />
        one binary, one small web layer
      </div>

      <CodePanel
        label="LOCAL   命令行"
        sub="ghc  haskeline  containers"
        x={120}
        delay={120}
        lines={[
          'git clone https://github.com/Xingye-Dujing/lambda-calculus-interpreter',
          'cd lambda-calculus-interpreter',
          './build.sh          # Windows: build.bat',
          './extension',
        ]}
      />
      <CodePanel
        label="WEB   网页"
        sub="flask  batch  json"
        x={1000}
        delay={240}
        lines={[
          'pip install -r web/requirements.txt',
          'python web/app.py',
          '# http://127.0.0.1:8081',
          '# 在线  online: http://47.116.114.77/lambda/',
          '# 每个会话保留一个常驻解释器',
        ]}
      />

      <div style={{position: 'absolute', left: 120, top: 730, width: 1680}}>
        <Reveal delay={520} y={10}>
          <Label color={C.faint}>A FEW COMMANDS   几条命令</Label>
        </Reveal>
        <div
          style={{
            marginTop: 16,
            display: 'flex',
            flexWrap: 'wrap',
            gap: 10,
            maxWidth: 1620,
          }}
        >
          {[
            ':trace',
            ':begin',
            ':step n',
            ':strategy',
            ':fast',
            ':type',
            ':ast',
            ':db',
            ':eq',
            ':conv',
            ':int',
            ':church',
          ].map((cmd, i) => (
            <CommandChip key={cmd} delay={560 + i * 18} active={i % 4 === 0}>
              {cmd}
            </CommandChip>
          ))}
        </div>
      </div>

      <div style={{position: 'absolute', left: 120, top: 850, width: 1680}}>
        <FlowDiagram frame={frame} />
      </div>
    </Stage>
  );
};
