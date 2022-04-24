const cryptodoge = require('../../util/cryptodoge');

describe('cryptodoge', () => {
  it('converts number mojo to cryptodoge', () => {
    const result = cryptodoge.mojo_to_cryptodoge(1000000);

    expect(result).toBe(0.000001);
  });
  it('converts string mojo to cryptodoge', () => {
    const result = cryptodoge.mojo_to_cryptodoge('1000000');

    expect(result).toBe(0.000001);
  });
  it('converts number mojo to cryptodoge string', () => {
    const result = cryptodoge.mojo_to_cryptodoge_string(1000000);

    expect(result).toBe('0.000001');
  });
  it('converts string mojo to cryptodoge string', () => {
    const result = cryptodoge.mojo_to_cryptodoge_string('1000000');

    expect(result).toBe('0.000001');
  });
  it('converts number cryptodoge to mojo', () => {
    const result = cryptodoge.cryptodoge_to_mojo(0.000001);

    expect(result).toBe(1000000);
  });
  it('converts string cryptodoge to mojo', () => {
    const result = cryptodoge.cryptodoge_to_mojo('0.000001');

    expect(result).toBe(1000000);
  });
  it('converts number mojo to colouredcoin', () => {
    const result = cryptodoge.mojo_to_colouredcoin(1000000);

    expect(result).toBe(1000);
  });
  it('converts string mojo to colouredcoin', () => {
    const result = cryptodoge.mojo_to_colouredcoin('1000000');

    expect(result).toBe(1000);
  });
  it('converts number mojo to colouredcoin string', () => {
    const result = cryptodoge.mojo_to_colouredcoin_string(1000000);

    expect(result).toBe('1,000');
  });
  it('converts string mojo to colouredcoin string', () => {
    const result = cryptodoge.mojo_to_colouredcoin_string('1000000');

    expect(result).toBe('1,000');
  });
  it('converts number colouredcoin to mojo', () => {
    const result = cryptodoge.colouredcoin_to_mojo(1000);

    expect(result).toBe(1000000);
  });
  it('converts string colouredcoin to mojo', () => {
    const result = cryptodoge.colouredcoin_to_mojo('1000');

    expect(result).toBe(1000000);
  });
});
