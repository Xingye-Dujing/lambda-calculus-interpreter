import React, {ReactNode} from 'react';
import {
  AbsoluteFill,
  Easing,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {C, EASE, FONT_LATIN, FONT_MONO, FONT_SERIF} from '../theme';

const ease = Easing.bezier(EASE[0], EASE[1], EASE[2], EASE[3]);

export const clamp = {
  extrapolateLeft: 'clamp',
  extrapolateRight: 'clamp',
} as const;

export const inOut = (frame: number, start: number, duration: number) => {
  return interpolate(frame, [start, start + duration], [0, 1], {
    ...clamp,
    easing: ease,
  });
};

export const fadeInOut = (
  frame: number,
  duration: number,
  inDuration = 18,
  outDuration = 18,
) => {
  const fadeIn = interpolate(frame, [0, inDuration], [0, 1], {
    ...clamp,
    easing: ease,
  });
  const fadeOut = interpolate(
    frame,
    [duration - outDuration, duration],
    [1, 0],
    {...clamp, easing: ease},
  );
  return Math.min(fadeIn, fadeOut);
};

export const Reveal: React.FC<{
  children: ReactNode;
  delay?: number;
  duration?: number;
  y?: number;
  x?: number;
  blur?: number;
  style?: React.CSSProperties;
}> = ({children, delay = 0, duration = 24, y = 22, x = 0, blur = 0, style}) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [delay, delay + duration], [0, 1], {
    ...clamp,
    easing: ease,
  });
  return (
    <div
      style={{
        opacity: p,
        transform: `translate3d(${(1 - p) * x}px, ${(1 - p) * y}px, 0)`,
        filter: blur ? `blur(${(1 - p) * blur}px)` : undefined,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

export const Rule: React.FC<{
  delay?: number;
  duration?: number;
  color?: string;
  thickness?: number;
  style?: React.CSSProperties;
}> = ({delay = 0, duration = 34, color = C.borderStrong, thickness = 1, style}) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [delay, delay + duration], [0, 1], {
    ...clamp,
    easing: ease,
  });
  return (
    <svg
      width="100%"
      height={thickness}
      viewBox="0 0 100 1"
      preserveAspectRatio="none"
      style={{display: 'block', overflow: 'visible', ...style}}
    >
      <line
        x1={0}
        y1={0.5}
        x2={100 * p}
        y2={0.5}
        stroke={color}
        strokeWidth={thickness}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
};

export const LambdaGlyph: React.FC<{
  size?: number;
  delay?: number;
  duration?: number;
  color?: string;
  style?: React.CSSProperties;
}> = ({size = 180, delay = 0, duration = 34, color = C.text, style}) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [delay, delay + duration], [0, 1], {
    ...clamp,
    easing: ease,
  });
  return (
    <div
      style={{
        fontFamily: FONT_LATIN,
        fontSize: size,
        lineHeight: 1,
        color,
        opacity: p,
        transform: `translateY(${(1 - p) * size * 0.04}px) scale(${0.96 + p * 0.04})`,
        ...style,
      }}
    >
      λ
    </div>
  );
};

export const Typewriter: React.FC<{
  text: string;
  delay?: number;
  speed?: number;
  style?: React.CSSProperties;
  cursor?: boolean;
  cursorColor?: string;
}> = ({text, delay = 0, speed = 1.1, style, cursor = true, cursorColor = C.text}) => {
  const frame = useCurrentFrame();
  const count = Math.max(
    0,
    Math.min(text.length, Math.floor(Math.max(0, frame - delay) * speed)),
  );
  const visible = text.slice(0, count);
  const done = count >= text.length;
  const blink = Math.floor(frame / 9) % 2 === 0;
  return (
    <span style={{whiteSpace: 'pre-wrap', ...style}}>
      {visible}
      {cursor && (!done || blink) ? (
        <span style={{color: cursorColor, opacity: done && !blink ? 0 : 1}}>▌</span>
      ) : null}
    </span>
  );
};

export const Label: React.FC<{
  children: ReactNode;
  color?: string;
  style?: React.CSSProperties;
}> = ({children, color = C.dim, style}) => (
  <div
    style={{
      fontFamily: FONT_MONO,
      fontSize: 15,
      letterSpacing: '0.22em',
      textTransform: 'uppercase',
      color,
      lineHeight: 1.4,
      ...style,
    }}
  >
    {children}
  </div>
);

export const Pill: React.FC<{
  children: ReactNode;
  active?: boolean;
  dark?: boolean;
  style?: React.CSSProperties;
}> = ({children, active = false, dark = false, style}) => (
  <span
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      border: `1px solid ${
        active ? (dark ? C.darkBorderStrong : C.borderStrong) : dark ? C.darkBorder : C.border
      }`,
      color: active ? (dark ? C.darkText : C.text) : dark ? C.darkDim : C.dim,
      fontFamily: FONT_MONO,
      fontSize: 18,
      lineHeight: 1,
      padding: '10px 14px 11px',
      borderRadius: 2,
      whiteSpace: 'nowrap',
      ...style,
    }}
  >
    {children}
  </span>
);

export const Panel: React.FC<{
  children: ReactNode;
  dark?: boolean;
  style?: React.CSSProperties;
  padding?: number | string;
}> = ({children, dark = false, style, padding = 28}) => (
  <div
    style={{
      border: `1px solid ${dark ? C.darkBorder : C.border}`,
      background: dark ? C.darkPaper : C.paper,
      borderRadius: 2,
      padding,
      ...style,
    }}
  >
    {children}
  </div>
);

export const CodeLine: React.FC<{
  children: ReactNode;
  size?: number;
  color?: string;
  style?: React.CSSProperties;
}> = ({children, size = 30, color = C.text, style}) => (
  <div
    style={{
      fontFamily: FONT_MONO,
      fontSize: size,
      lineHeight: 1.8,
      color,
      whiteSpace: 'pre',
      ...style,
    }}
  >
    {children}
  </div>
);

export const CodeBlock: React.FC<{
  lines: ReactNode[];
  size?: number;
  color?: string;
  gap?: number;
  style?: React.CSSProperties;
}> = ({lines, size = 30, color = C.text, gap = 0, style}) => (
  <div style={{display: 'flex', flexDirection: 'column', gap, ...style}}>
    {lines.map((line, i) => (
      <CodeLine key={i} size={size} color={color}>
        {line}
      </CodeLine>
    ))}
  </div>
);

export const Stage: React.FC<{
  children: ReactNode;
  dark?: boolean;
  grid?: boolean;
  style?: React.CSSProperties;
}> = ({children, dark = false, grid = true, style}) => (
  <AbsoluteFill
    style={{
      background: dark ? C.dark : C.bg,
      color: dark ? C.darkText : C.text,
      fontFamily: FONT_SERIF,
      overflow: 'hidden',
      ...style,
    }}
  >
    {grid ? (
      <div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage: `linear-gradient(to right, ${
            dark ? 'rgba(255,255,255,0.035)' : 'rgba(20,21,24,0.035)'
          } 1px, transparent 1px), linear-gradient(to bottom, ${
            dark ? 'rgba(255,255,255,0.035)' : 'rgba(20,21,24,0.035)'
          } 1px, transparent 1px)`,
          backgroundSize: '96px 96px',
          maskImage:
            'radial-gradient(ellipse at 50% 45%, black 0%, black 58%, transparent 100%)',
        }}
      />
    ) : null}
    <div style={{position: 'absolute', inset: 0}}>{children}</div>
  </AbsoluteFill>
);

export const SceneMeta: React.FC<{
  chapter: string;
  index: string;
  dark?: boolean;
  right?: string;
}> = ({chapter, index, dark = false, right = 'HASKELL   λ'}) => {
  const color = dark ? C.darkFaint : C.faint;
  const line = dark ? C.darkBorder : C.border;
  return (
    <>
      <div
        style={{
          position: 'absolute',
          top: 56,
          left: 80,
          right: 80,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          borderBottom: `1px solid ${line}`,
          paddingBottom: 18,
          color,
          fontFamily: FONT_MONO,
          fontSize: 15,
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
        }}
      >
        <span>
          <span style={{display: 'flex', gap: 18, alignItems: 'baseline'}}>
            <span>{index}</span>
            <span>{chapter}</span>
          </span>
        </span>
        <span>{right}</span>
      </div>
      <div
        style={{
          position: 'absolute',
          bottom: 48,
          left: 80,
          right: 80,
          display: 'flex',
          justifyContent: 'space-between',
          color,
          fontFamily: FONT_MONO,
          fontSize: 14,
          letterSpacing: '0.16em',
          textTransform: 'uppercase',
        }}
      >
        <span>Lambda Calculus Interpreter</span>
        <span>λ → ⇒</span>
      </div>
    </>
  );
};

export const Kicker: React.FC<{
  children: ReactNode;
  dark?: boolean;
  delay?: number;
}> = ({children, dark = false, delay = 0}) => (
  <Reveal delay={delay} y={10} duration={18}>
    <Label color={dark ? C.darkFaint : C.faint}>{children}</Label>
  </Reveal>
);

export const Display: React.FC<{
  children: ReactNode;
  size?: number;
  style?: React.CSSProperties;
}> = ({children, size = 82, style}) => (
  <div
    style={{
      fontFamily: FONT_SERIF,
      fontSize: size,
      lineHeight: 1.28,
      fontWeight: 400,
      letterSpacing: '0.01em',
      ...style,
    }}
  >
    {children}
  </div>
);

export const Latin: React.FC<{
  children: ReactNode;
  size?: number;
  style?: React.CSSProperties;
}> = ({children, size = 82, style}) => (
  <div
    style={{
      fontFamily: FONT_LATIN,
      fontSize: size,
      lineHeight: 1.2,
      fontWeight: 400,
      letterSpacing: '-0.01em',
      ...style,
    }}
  >
    {children}
  </div>
);
