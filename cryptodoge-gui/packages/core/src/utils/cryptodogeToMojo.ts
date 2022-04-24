import Big from 'big.js';
import Unit from '../constants/Unit';
import cryptodogeFormatter from './cryptodogeFormatter';

export default function cryptodogeToMojo(cryptodoge: string | number | Big): number {
  return cryptodogeFormatter(cryptodoge, Unit.CRYPTODOGE)
    .to(Unit.MOJO)
    .toNumber();
}
