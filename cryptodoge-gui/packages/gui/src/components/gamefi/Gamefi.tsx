import React from 'react';
import styled, { createGlobalStyle } from 'styled-components';
import { Flex, Link, DashboardTitle } from '@cryptodoge/core';
import { Trans } from '@lingui/macro';
import { Route, Routes } from 'react-router-dom';
import useOpenExternal from '../../hooks/useOpenExternal';

import {
  Button,
  MenuItem,
  Box,
  ListItemIcon,
  Typography,
} from '@material-ui/core';


import gamebg1 from '../../assets/img/bg1.jpg';
import gamebg2 from '../../assets/img/bg2.jpg';
import gamebg3 from '../../assets/img/bg3.jpg';
import gamebg4 from '../../assets/img/bg4.jpg';


const StyledPicContainer = styled.div`
    float:left;
  img {
    height: 280px;
    margin-right: 10px;
  }
`;
const StyledDiv = styled.div`
    width:100%;
    margin: 0 auto; 
    text-align: center
`;

export default function Gamefi() {

  const openExternal = useOpenExternal();
  function openGamefi() {
      openExternal('https://gamefi.cryptodoge.cc/');
  }

    return (
    <> 
      <DashboardTitle>
        <Trans>Cryptodoge's Gamefi-MetaDoge!</Trans>
      </DashboardTitle>
      <div>
          <StyledPicContainer>
            <img src={gamebg1} />
          </StyledPicContainer>

          <StyledPicContainer>
            <img src={gamebg2} />
          </StyledPicContainer>

          <StyledPicContainer>
            <img src={gamebg3} />
          </StyledPicContainer>

           <StyledPicContainer>
            <img src={gamebg4} />
          </StyledPicContainer>
      </div>
      <StyledDiv  > 
          <Button onClick={openGamefi} variant="contained"  color="primary">
            <Trans>Play Gamefi</Trans>
          </Button>
      </StyledDiv>
    </>


  );
}
