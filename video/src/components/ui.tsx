import React, {ReactNode} from 'react';
import {interpolate, staticFile, useCurrentFrame} from 'remotion';
import {C, FONT_MONO} from '../theme';
import {clamp, inOut, Reveal} from './core';

export const FontFaces: React.FC = () => {
  return (
    <style>{`
      @font-face {
        font-family: 'APL385 Unicode';
        src: url('${staticFile('fonts/APL385.ttf')}') format('truetype');
        font-display: block;
      }
      @font-face {
        font-family: 'LXGW WenKai GB';
        src: url('${staticFile('fonts/LXGWWenKaiGB-Subset.ttf')}') format('truetype');
        font-display: block;
        font-weight: 400;
      }
    `}</style>
  );
};

export const AppWindow: React.FC<{
  children: ReactNode;
  activeTab?: string;
  width?: number | string;
  height?: number | string;
  status?: string;
  style?: React.CSSProperties;
}> = ({
  children,
  activeTab = '轨迹',
  width = 1500,
  height = 650,
  status = '已连接  connected',
  style,
}) => {
  const tabs = ['轨迹', '结构', '类型', '环境', '工具', '帮助', '指引'];
  return (
    <div
      style={{
        width,
        height,
        border: `1px solid ${C.borderStrong}`,
        background: C.paper,
        display: 'flex',
        flexDirection: 'column',
        borderRadius: 2,
        overflow: 'hidden',
        ...style,
      }}
    >
      <div
        style={{
          height: 58,
          flex: 'none',
          borderBottom: `1px solid ${C.border}`,
          display: 'flex',
          alignItems: 'center',
          padding: '0 22px',
          gap: 14,
          fontFamily: FONT_MONO,
          fontSize: 17,
          color: C.dim,
          letterSpacing: '0.08em',
        }}
      >
        <span style={{color: C.text}}>LAMBDA-REPL</span>
        <span style={{color: C.faint, fontSize: 14, letterSpacing: '0.12em'}}>
          HASKELL
        </span>
        <span style={{flex: 1}} />
        <span style={{display: 'inline-flex', alignItems: 'center', gap: 8}}>
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: 99,
              background: C.ok,
              display: 'inline-block',
            }}
          />
          {status}
        </span>
      </div>
      <div
        style={{
          height: 54,
          flex: 'none',
          borderBottom: `1px solid ${C.border}`,
          display: 'flex',
          alignItems: 'stretch',
          padding: '0 14px',
          gap: 4,
        }}
      >
        {tabs.map((tab) => (
          <div
            key={tab}
            style={{
              padding: '0 16px',
              display: 'flex',
              alignItems: 'center',
              borderBottom:
                tab === activeTab ? `1px solid ${C.text}` : '1px solid transparent',
              color: tab === activeTab ? C.text : C.faint,
              fontFamily: FONT_MONO,
              fontSize: 18,
            }}
          >
            {tab}
          </div>
        ))}
        <div style={{flex: 1}} />
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            color: C.faint,
            fontFamily: FONT_MONO,
            fontSize: 15,
          }}
        >
          浅色  light
        </div>
      </div>
      <div style={{flex: 1, minHeight: 0, display: 'flex'}}>{children}</div>
    </div>
  );
};

export const TermLine: React.FC<{
  children: ReactNode;
  prompt?: string;
  tone?: 'normal' | 'result' | 'dim' | 'error' | 'warn';
  size?: number;
  style?: React.CSSProperties;
  delay?: number;
}> = ({children, prompt, tone = 'normal', size = 25, style, delay = 0}) => {
  const color =
    tone === 'result'
      ? C.text
      : tone === 'dim'
        ? C.dim
        : tone === 'error'
          ? C.err
          : tone === 'warn'
            ? C.warn
            : C.text;
  return (
    <Reveal delay={delay} y={8} duration={16}>
      <div
        style={{
          display: 'flex',
          gap: 10,
          fontFamily: FONT_MONO,
          fontSize: size,
          lineHeight: 1.6,
          color,
          whiteSpace: 'pre-wrap',
          ...style,
        }}
      >
        {prompt ? (
          <span style={{color: C.text, flex: 'none', fontWeight: 600}}>{prompt}</span>
        ) : null}
        <span style={{minWidth: 0}}>{children}</span>
      </div>
    </Reveal>
  );
};

export const MiniTrace: React.FC<{
  step: number;
  total: number;
  rule: string;
  before: string;
  after: string;
  delay?: number;
  width?: number;
}> = ({step, total, rule, before, after, delay = 0, width = 520}) => {
  const frame = useCurrentFrame();
  const p = inOut(frame, delay, 20);
  return (
    <Reveal delay={delay} y={12} duration={18}>
      <div style={{width, opacity: p}}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
            color: C.dim,
            fontFamily: FONT_MONO,
            fontSize: 15,
            letterSpacing: '0.08em',
            marginBottom: 14,
          }}
        >
          <span>
            {rule} 归约  reduction
          </span>
          <span>
            第 {step} 步  共 {total} 步
          </span>
        </div>
        <div
          style={{
            border: `1px solid ${C.border}`,
            padding: '14px 16px',
            marginBottom: 10,
            background: C.bg,
          }}
        >
          <div
            style={{
              fontFamily: FONT_MONO,
              fontSize: 12,
              letterSpacing: '0.14em',
              color: C.faint,
              marginBottom: 8,
            }}
          >
            BEFORE  归约前
          </div>
          <div
            style={{
              fontFamily: FONT_MONO,
              fontSize: 17,
              lineHeight: 1.55,
              color: C.dim,
              whiteSpace: 'pre-wrap',
            }}
          >
            {before}
          </div>
        </div>
        <div
          style={{
            border: `1px solid ${C.border}`,
            padding: '14px 16px',
            background: C.bg,
          }}
        >
          <div
            style={{
              fontFamily: FONT_MONO,
              fontSize: 12,
              letterSpacing: '0.14em',
              color: C.faint,
              marginBottom: 8,
            }}
          >
            AFTER  归约后
          </div>
          <div
            style={{
              fontFamily: FONT_MONO,
              fontSize: 17,
              lineHeight: 1.55,
              color: C.text,
              whiteSpace: 'pre-wrap',
            }}
          >
            {after}
          </div>
        </div>
      </div>
    </Reveal>
  );
};

export const RedexRow: React.FC<{
  index: number;
  path: string;
  term: string;
  active?: boolean;
  delay?: number;
  onClickPulse?: number;
}> = ({index, path, term, active = false, delay = 0, onClickPulse = 0}) => {
  const frame = useCurrentFrame();
  const pulse = interpolate(
    frame,
    [onClickPulse, onClickPulse + 8, onClickPulse + 28],
    [0, 1, 0],
    clamp,
  );
  return (
    <Reveal delay={delay} y={8} duration={16}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          padding: '9px 12px',
          border: `1px solid ${active ? C.borderStrong : C.border}`,
          borderLeft: `2px solid ${active ? C.text : C.border}`,
          background: active ? C.wash : 'transparent',
          boxShadow: pulse > 0 ? `0 0 0 ${4 + pulse * 4}px rgba(20,21,24,0.06)` : undefined,
          fontFamily: FONT_MONO,
          fontSize: 19,
          color: active ? C.text : C.dim,
          marginBottom: 8,
        }}
      >
        <span style={{color: C.faint, width: 20}}>{index}</span>
        <span style={{color: C.faint, width: 54}}>{path}</span>
        <span
          style={{
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {term}
        </span>
        {active ? (
          <span
            style={{
              marginLeft: 'auto',
              fontSize: 12,
              letterSpacing: '0.14em',
              color: C.faint,
            }}
          >
            SELECTED
          </span>
        ) : null}
      </div>
    </Reveal>
  );
};

export const Cursor: React.FC<{
  x: number;
  y: number;
  fromX?: number;
  fromY?: number;
  delay?: number;
  duration?: number;
  clickAt?: number;
  dark?: boolean;
}> = ({
  x,
  y,
  fromX = x + 220,
  fromY = y + 260,
  delay = 0,
  duration = 32,
  clickAt,
  dark = false,
}) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [delay, delay + duration], [0, 1], {
    ...clamp,
    easing: (t) => 1 - Math.pow(1 - t, 3),
  });
  const click = clickAt
    ? interpolate(frame, [clickAt, clickAt + 18], [1, 0], clamp)
    : 0;
  const scale = clickAt
    ? interpolate(frame, [clickAt - 6, clickAt, clickAt + 6], [1, 0.86, 1], clamp)
    : 1;
  return (
    <div
      style={{
        position: 'absolute',
        left: fromX + (x - fromX) * p,
        top: fromY + (y - fromY) * p,
        width: 34,
        height: 40,
        transform: `scale(${scale})`,
        transformOrigin: 'top left',
        pointerEvents: 'none',
      }}
    >
      {click > 0 ? (
        <div
          style={{
            position: 'absolute',
            left: -18,
            top: -18,
            width: 70,
            height: 70,
            borderRadius: 99,
            border: `1px solid ${dark ? C.darkText : C.text}`,
            opacity: click * 0.45,
            transform: `scale(${1 + (1 - click) * 0.8})`,
          }}
        />
      ) : null}
      <svg width="30" height="38" viewBox="0 0 30 38">
        <path
          d="M 2 2 L 2 29 L 9 22 L 14 34 L 20 31 L 15 20 L 25 20 Z"
          fill={dark ? C.darkText : C.text}
          stroke={dark ? C.dark : C.paper}
          strokeWidth={1.4}
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
};

export const CommandChip: React.FC<{
  children: ReactNode;
  active?: boolean;
  delay?: number;
}> = ({children, active = false, delay = 0}) => (
  <Reveal delay={delay} y={10} duration={16}>
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        border: `1px solid ${active ? C.borderStrong : C.border}`,
        color: active ? C.text : C.dim,
        background: active ? C.wash : 'transparent',
        fontFamily: FONT_MONO,
        fontSize: 20,
        padding: '9px 13px',
        lineHeight: 1,
        borderRadius: 2,
      }}
    >
      {children}
    </span>
  </Reveal>
);

