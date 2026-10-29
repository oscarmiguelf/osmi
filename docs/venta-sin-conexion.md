# Vender sin conexión

[← Volver al manual](README.md)

Si se va el internet, el dispositivo del punto de venta puede seguir cobrando con los precios que tenía guardados. Las ventas se guardan en el equipo y se envían solas cuando vuelve la conexión.

## Preparar el dispositivo (una sola vez)

1. [Instala la app](primeros-pasos.md#instalar-la-app) en el equipo de la caja.
2. Con internet, **ocupa tu caja** y abre el punto de venta. El equipo guarda una copia de productos, precios, listas de precios, clientes y formas de pago, y la actualiza sola mientras hay conexión.

## Cobrar sin internet

1. Abre Osmi. Sin conexión aparece la pantalla **Venta sin conexión**, con tu caja y tu nombre arriba.
2. Busca el producto o escanea su código de barras.
3. **Cliente (opcional):** si lo eliges, se aplican sus precios.
4. Elige la **forma de pago** (efectivo, tarjeta o transferencia). Con efectivo, escribe lo **recibido** para ver el cambio.
5. Pulsa **Cobrar**. La venta se guarda en el equipo con un **folio temporal**, por ejemplo `OFF-K7QX-1`.
6. Si quieres, **Imprimir ticket**. Luego **Nueva venta**.

La lista **Ventas de este dispositivo** muestra las ventas guardadas y su estado: *Por enviar*, *Enviada* (con su folio real) o *No se pudo enviar* (con el motivo).

## Cuando vuelve el internet

- Las ventas se envían solas con su hora original y reciben su **folio real**. También puedes pulsar **Enviar ahora**.
- La venta se puede buscar después por el folio real o por el temporal.
- Para enviarlas tienes que estar **ocupando la misma caja con tu usuario**. Si alguien soltó esa caja, ocúpala de nuevo.
- Si cierras sesión, las ventas pendientes no se pierden: se envían cuando vuelvas a entrar con tu usuario.

## Qué no se puede hacer sin conexión

- Ventas a crédito o apartados.
- Promociones, paquetes y membresías.
- Devoluciones.
- Más de una forma de pago en la misma venta.
- Enviar el ticket por WhatsApp (sí se puede imprimir).

## Si algo no cuadra al enviarse

El cliente ya pagó, así que la venta **siempre se registra**. Si se vendió algo que ya no había (otra caja lo vendió mientras tanto) o el precio cambió, la venta aparece en **Ventas → Ventas sin conexión por revisar**:

- **Existencia:** se vendió más de lo que había; la existencia queda en negativo hasta que se haga un conteo o un ajuste.
- **Precio:** se cobró con el precio que tenía guardado el equipo.

Un encargado revisa cada caso, hace el ajuste que haga falta y pulsa **Marcar revisada** (con una nota opcional). La venta muestra la etiqueta *Vendida sin conexión · folio temporal …*.

## Datos guardados en el dispositivo

El equipo guarda el catálogo y los nombres de los clientes (sin teléfonos). Al cerrar sesión se borra esa copia; las ventas pendientes se conservan hasta enviarse.
