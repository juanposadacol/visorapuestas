
test('formato vertical: la cuota hereda el lado de su cabecera', () => {
  // Asi llega desde el DOM: cada celda es un nodo de texto independiente.
  const { lines } = parseLines('Más de 140.5\n1.32\nMenos de 140.5\n2.85');
  const fundidas = dedupeLines(lines).lines;
  assert.equal(fundidas.length, 1);
  assert.equal(fundidas[0].overOdds, 1.32);
  assert.equal(fundidas[0].underOdds, 2.85);
});

test('varias lineas en formato vertical con lados separados', () => {
  const texto = [
    'Más de 158.5', '1.80', 'Menos de 158.5', '1.95',
    'Más de 159.5', '1.90', 'Menos de 159.5', '1.85',
  ].join('\n');
  const fundidas = dedupeLines(parseLines(texto).lines).lines;
  assert.equal(fundidas.length, 2);
  assert.deepEqual(fundidas.map((l) => [l.line, l.overOdds, l.underOdds]),
                   [[158.5, 1.80, 1.95], [159.5, 1.90, 1.85]]);
});
