import React from 'react';
import {Composition} from 'remotion';
import {FPS, HEIGHT, WIDTH} from './theme';
import {LambdaPromo, TOTAL_FRAMES} from './LambdaPromo';
import {Cover} from './Cover';
import {
  BiliPromo,
  BILI_FRAMES,
  DouyinPromo,
  DOUYIN_FRAMES,
} from './FootageFilm';

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="LambdaPromo"
        component={LambdaPromo}
        durationInFrames={TOTAL_FRAMES}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
      />
      <Composition
        id="Cover"
        component={Cover}
        durationInFrames={1}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
      />
      <Composition
        id="BiliPromo"
        component={BiliPromo}
        durationInFrames={BILI_FRAMES}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
      />
      <Composition
        id="DouyinPromo"
        component={DouyinPromo}
        durationInFrames={DOUYIN_FRAMES}
        fps={FPS}
        width={1080}
        height={1920}
      />
    </>
  );
};
