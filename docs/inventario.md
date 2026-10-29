# Inventario

[← Volver al manual](README.md)

La existencia es de cada sucursal y solo cambia con movimientos: ventas, compras, devoluciones, ajustes, traspasos y conteos. Nadie la escribe a mano.

## Existencias

**Inventario** tiene dos pestañas:

- **Existencias:** los productos con existencia en la sucursal donde trabajas, con su mínimo y su costo.
- **Movimientos:** cada entrada y salida (venta, compra, ajuste, devolución, traspaso enviado o recibido) con la existencia resultante.

Para ver todos los movimientos de un solo producto usa el reporte **Kárdex de un producto** (ver [Reportes](reportes.md)).

### Ajustar existencia

En un producto, **Ajustar existencia**: un número positivo para sumar y negativo para restar (merma, robo, error de captura), con una nota. Para corregir muchos productos a la vez es mejor un [conteo físico](#conteos-físicos).

## Compras

**Compras → Registrar compra.** Lo que llega de tus proveedores; la existencia sube al guardar.

1. **Proveedor** y fecha (vacía = hoy).
2. Productos con cantidad y **costo unitario** (solo productos con existencia; no servicios ni kits). Al elegir un producto se muestra su último costo y proveedor.
3. **Cómo se pagó**, se puede repartir:
   - **De la caja:** sale efectivo de la caja que ocupas (necesitas una ocupada y que alcance).
   - **De otra forma:** dinero propio, transferencia, tarjeta… no sale de la caja.
   - **Queda a deber:** lo que falta.
4. **Guardar compra.**

Después, en la compra se puede **pagar lo que se debe**, editar los datos generales o **anularla**. Los productos, cantidades y costos no se editan: si están mal, se anula la compra (la existencia y el costo promedio regresan a como estaban) y se registra de nuevo.

La pestaña **Resumen** muestra las compras del periodo por proveedor.

## Proveedores

**Proveedores:** contacto, los productos que surte cada uno (con su historial de costos), el total comprado y sus últimas compras. Al crear uno, el sistema avisa si ya existe un nombre parecido. Se eliminan y restauran desde la lista.

## Traspasos

Para mover mercancía entre sucursales.

1. **Traspasos → Enviar traspaso:** la sucursal destino y los productos con cantidad (solo productos con existencia en tu sucursal). Al enviarlo, la mercancía sale de tu sucursal y queda **en camino**.
2. En la sucursal destino aparece el aviso de traspasos en camino. Al llegar, **Recibir**: la mercancía se suma tal como se envió. Si llegó algo diferente, se corrige después con un ajuste.
3. Mientras está en camino, el envío se puede **cancelar** y la mercancía regresa a la sucursal de origen.

## Conteos físicos

Para comparar lo que hay en el anaquel contra el sistema y corregir la existencia.

1. **Conteos físicos → Iniciar conteo** (con una nota, por ejemplo "Conteo mensual, pasillo 3"). Solo puede haber un conteo abierto por sucursal.
2. **Contar:** escanea el código (o busca), escribe la cantidad y Enter. Quien cuenta **no ve** las cantidades del sistema (conteo ciego).
3. El supervisor ve las pestañas **Contados**, **Diferencias** y **Sin contar**.
4. **Completar conteo:** la existencia de cada producto contado queda **igual a lo contado**. Los productos que no se contaron no se tocan. No se puede deshacer.

Lo ideal es contar sin vender. Si se vende mientras se cuenta, al completar gana lo contado. **Cancelar** un conteo no cambia ninguna existencia.

## Reportes de inventario

Valor del inventario, existencias bajas, productos sin movimiento, movimientos, mermas, kárdex, resultados de conteos y traspasos: ver [Reportes](reportes.md).
