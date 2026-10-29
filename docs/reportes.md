# Reportes

[← Volver al manual](README.md)

## Hoy

La entrada de **Reportes** muestra el día en la sucursal donde trabajas:

- Tickets, venta neta y ticket promedio, comparados con ayer y con el mismo día de la semana pasada.
- **Existencias bajas** y **Por cobrar**, con enlace al detalle.
- **Lo más vendido hoy.**
- **Efectivo y saldos en cajas.**

## El catálogo de reportes

Debajo, los reportes por sección. Cada uno tiene sus filtros (sucursales, periodo de hasta 366 días, agrupar por día, semana o mes, y lo que pida el reporte), una tabla con totales y **Exportar CSV** o **Exportar a Excel**. Cada exportación queda registrada.

### Ventas

| Reporte | Qué muestra |
|---|---|
| Resumen de ventas | Tickets, ventas, descuentos, IVA, devoluciones y neto por periodo |
| Ventas por forma de pago | Lo cobrado y lo reembolsado con cada forma de pago |
| Ventas por vendedor | Tickets, venta y ticket promedio de cada vendedor |
| Mejores clientes | Los 100 clientes que más compraron |
| Ventas por categoría | Unidades, venta, costo y margen por categoría |
| Productos más y menos vendidos | Unidades, venta, costo y margen por producto |
| Ventas por hora | Mapa de calor por día de la semana y hora, para planear turnos |
| Descuentos y promociones | Descuentos a la venta, por renglón y por promoción |
| Devoluciones | Cada devolución con su venta, motivo y quién la hizo |
| Impuestos por tasa | Base e IVA de lo vendido por tasa |
| Entregas pendientes | Apartados por entregar y cuántos días llevan |

### Caja y pagos

| Reporte | Qué muestra |
|---|---|
| Movimientos de caja | Entradas, retiros, ventas y devoluciones por caja y forma de pago |
| Cortes de caja | Esperado contra contado y diferencia de cada corte |
| Saldos de caja | Saldo actual de cada caja por forma de pago |
| Abonos cobrados | Abonos por día, forma de pago y quién los cobró |

### Crédito

| Reporte | Qué muestra |
|---|---|
| Cuentas por cobrar | Lo que debe cada cliente, por antigüedad (0–30, 31–60, 61–90, más de 90 días) |
| Estado de cuenta | Cargos, abonos y devoluciones de un cliente con su saldo |

### Inventario

| Reporte | Qué muestra |
|---|---|
| Valor del inventario | Existencia actual a costo y a precio, por sucursal y categoría |
| Existencias bajas | Productos en o por debajo de su mínimo |
| Productos sin movimiento | Con existencia y sin ventas en los últimos N días |
| Movimientos de inventario | Movimientos por tipo, en unidades y a costo |
| Mermas | Ajustes negativos (incluidos los de conteos), a costo |
| Kárdex de un producto | Cada movimiento de un producto con la existencia resultante |
| Resultados de conteos | Sobrantes y faltantes a costo de cada conteo |
| Traspasos | Traspasos por ruta y estado |

### Compras

| Reporte | Qué muestra |
|---|---|
| Compras por proveedor | Número de compras y total por proveedor |
| Compras por producto | Unidades, total, costo promedio, último costo y costo actual |
| Historial de costo | Cada compra de un producto con su costo unitario |

### Seguridad (administradores)

Accesos al sistema, exportaciones de reportes e intentos fallidos de acceso.

## Notas sobre los números

- La **venta** de los reportes de margen va sin IVA y con el descuento de la venta repartido entre sus renglones.
- El **IVA oficial** es la suma del IVA de cada venta; el desglose por tasa puede diferir por centavos de redondeo.
- Las citas con servicios generan su venta al agendarse, así que las ventas de citas futuras aparecen en los reportes desde que se agendan.
