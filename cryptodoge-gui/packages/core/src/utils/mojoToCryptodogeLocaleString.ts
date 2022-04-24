import Big from 'big.js';
import Unit from '../constants/Unit';
import cryptodogeFormatter from './cryptodogeFormatter';

export default function mojoToCryptodogeLocaleString(mojo: string | number | Big) {
  return cryptodogeFormatter(Number(mojo), Unit.MOJO)
    .to(Unit.CRYPTODOGE)
    .toLocaleString();
}
