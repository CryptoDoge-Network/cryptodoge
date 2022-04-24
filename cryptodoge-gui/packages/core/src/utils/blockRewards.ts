import Big from 'big.js';

const MOJO_PER_CRYPTODOGE = Big('1000000');
const BLOCKS_PER_YEAR = 1681920;
const POOL_REWARD = '0.875'; // 7 / 8
const FARMER_REWARD = '0.125'; // 1 /8

export function calculatePoolReward(height: number): Big {
  if (height === 0) {
    return MOJO_PER_CRYPTODOGE.times('21000000000').times(POOL_REWARD);
  } 
  if (height < 3 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('2').times(POOL_REWARD).times('10000');
  }
  if (height < 6 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('1').times(POOL_REWARD).times('10000');
  }
  if (height < 9 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.5').times(POOL_REWARD).times('10000');
  }
  if (height < 12 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.25').times(POOL_REWARD).times('10000');
  }
  if (height < 15 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.125').times(POOL_REWARD).times('10000');
  }
  if (height < 18 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.0625').times(POOL_REWARD).times('10000');
  }
  if (height < 21 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.03125').times(POOL_REWARD).times('10000');
  }
  if (height < 24 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.015625').times(POOL_REWARD).times('10000');
  }
  if (height < 27 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.0078125').times(POOL_REWARD).times('10000');
  }
  if (height < 30 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.00390625').times(POOL_REWARD).times('10000');
  }
  if (height < 99 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('50').times(POOL_REWARD);
  }

  return MOJO_PER_CRYPTODOGE.times('0');
}

export function calculateBaseFarmerReward(height: number): Big {
  if (height === 0) {
    return MOJO_PER_CRYPTODOGE.times('21000000000').times(FARMER_REWARD);
  }
if (height < 3 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('2').times(FARMER_REWARD).times('10000');
  }
  if (height < 6 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('1').times(FARMER_REWARD).times('10000');
  }
  if (height < 9 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.5').times(FARMER_REWARD).times('10000');
  }
  if (height < 12 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.25').times(FARMER_REWARD).times('10000');
  }
  if (height < 15 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.125').times(FARMER_REWARD).times('10000');
  }
  if (height < 18 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.0625').times(FARMER_REWARD).times('10000');
  }
  if (height < 21 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.03125').times(FARMER_REWARD).times('10000');
  }
  if (height < 24 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.015625').times(FARMER_REWARD).times('10000');
  }
  if (height < 27 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.0078125').times(FARMER_REWARD).times('10000');
  }
  if (height < 30 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('0.00390625').times(FARMER_REWARD).times('10000');
  }
  if (height < 99 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times('50').times(FARMER_REWARD);
  }

  return MOJO_PER_CRYPTODOGE.times('0');
}
