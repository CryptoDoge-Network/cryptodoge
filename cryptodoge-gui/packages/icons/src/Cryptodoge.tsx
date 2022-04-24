import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import CryptodogeIcon from './images/cryptodoge.svg';

export default function Keys(props: SvgIconProps) {
  return <SvgIcon component={CryptodogeIcon} viewBox="0 0 200 200" {...props} />;
}
