import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import GamefiIcon from './images/gamefi.svg';

export default function Gamefi(props: SvgIconProps) {
  return <SvgIcon component={GamefiIcon} viewBox="0 0 32 39" {...props} />;
}
