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

1. **Traspasos → Enviar traspaso:** la sucursal destino, notas (opcional) y los productos con cantidad (busca el producto, escribe la cantidad y **Agregar**; solo productos con existencia en tu sucursal). Pulsa **Enviar**. El traspaso recibe un folio (por ejemplo `SUC1-T000001`), la mercancía sale de tu sucursal y queda **En tránsito**.
2. En la sucursal destino aparece el aviso "N traspasos en camino a esta sucursal". Al llegar la mercancía, abre el traspaso y pulsa **Recibir traspaso**: se suma tal como se envió. Si llegó algo diferente, se corrige después con un ajuste.
3. Mientras está en tránsito, la sucursal que lo envió puede **Cancelar traspaso** y la mercancía regresa a ella.

La lista se filtra por enviados o recibidos y por estado (en tránsito, recibido, cancelado).

## Conteos físicos

Para comparar lo que hay en el anaquel contra el sistema y corregir la existencia.

1. **Conteos físicos → Iniciar conteo** (con una nota, por ejemplo "Conteo mensual, pasillo 3"). Solo puede haber un conteo abierto por sucursal; aparece arriba de la lista para seguir contando.
2. **Contar** (permiso *Crear* de Conteos): escanea el código y Enter (o busca el producto), escribe la cantidad contada y Enter. Se guarda al momento y se puede seguir con el siguiente. Si un producto se cuenta dos veces, se corrige la cantidad.
3. Quien solo cuenta **no ve** las cantidades del sistema (conteo ciego). El supervisor (permiso *Editar* de Conteos) ve las pestañas **Contados**, **Diferencias** y **Sin contar**, con lo contado, lo que dice el sistema y la diferencia, y puede quitar un producto del conteo.
4. **Hoja de conteo (CSV)** descarga la lista de productos para contar en papel.
5. El supervisor pulsa **Completar conteo:** la existencia de cada producto contado queda **igual a lo contado**. Los productos que no se contaron no se tocan. No se puede deshacer.

Lo ideal es contar sin vender. Si se vende mientras se cuenta, al completar gana lo contado. **Cancelar** un conteo no cambia ninguna existencia.

## Reportes de inventario

Valor del inventario, existencias bajas, productos sin movimiento, movimientos, mermas, kárdex, resultados de conteos y traspasos: ver [Reportes](reportes.md).
