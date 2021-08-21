import Big from 'big.js';

const MOJO_PER_CRYPTODOGE = Big(1000000);
const BLOCKS_PER_YEAR = 1681920;

export function calculatePoolReward(height: number): Big {
  if (height === 0) {
    return MOJO_PER_CRYPTODOGE.times(21000000000).times(7 / 8);
  }
  if (height < 3 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(2).times(7 / 8).times(10000);
  }
  if (height < 6 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(1).times(7 / 8).times(10000);
  }
  if (height < 9 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.5).times(7 / 8).times(10000);
  }
  if (height < 12 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.25).times(7 / 8).times(10000);
  }
  if (height < 15 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.125).times(7 / 8).times(10000);
  }
  if (height < 18 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.0625).times(7 / 8).times(10000);
  }
  if (height < 21 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.03125).times(7 / 8).times(10000);
  }
  if (height < 24 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.015625).times(7 / 8).times(10000);
  }
  if (height < 27 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.0078125).times(7 / 8).times(10000);
  }
  if (height < 30 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.00390625).times(7 / 8).times(10000);
  }
  if (height < 99 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(50).times(7 / 8);
  }

  return MOJO_PER_CRYPTODOGE.times(0);
}

export function calculateBaseFarmerReward(height: number): Big {
  if (height === 0) {
    return MOJO_PER_CRYPTODOGE.times(21000000000).times(1 / 8);
  }
  if (height < 3 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(2).times(1 / 8).times(10000);
  }
  if (height < 6 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(1).times(1 / 8).times(10000);
  }
  if (height < 9 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.5).times(1 / 8).times(10000);
  }
  if (height < 12 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.25).times(1 / 8).times(10000);
  }
  if (height < 15 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.125).times(1 / 8).times(10000);
  }
  if (height < 18 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.0625).times(1 / 8).times(10000);
  }
  if (height < 21 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.03125).times(1 / 8).times(10000);
  }
  if (height < 24 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.015625).times(1 / 8).times(10000);
  }
  if (height < 27 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.0078125).times(1 / 8).times(10000);
  }
  if (height < 30 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(0.00390625).times(1 / 8).times(10000);
  }
  if (height < 99 * BLOCKS_PER_YEAR) {
    return MOJO_PER_CRYPTODOGE.times(50).times(1 / 8);
  }

  return MOJO_PER_CRYPTODOGE.times(0);
}
