import React from 'react';
import styled from 'styled-components';
import { Box, BoxProps } from '@material-ui/core';
import { Cryptodoge } from '@cryptodoge/icons';

const StyledCryptodoge = styled(Cryptodoge)`
  max-width: 100%;
  width: auto;
  height: auto;
`;

export default function Logo(props: BoxProps) {
  return (
    <Box {...props}>
      <StyledCryptodoge />
    </Box>
  );
}
