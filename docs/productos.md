# Productos

[← Volver al manual](README.md)

Los productos se comparten entre todas las sucursales; la existencia es de cada sucursal.

## Tipos

- **Producto:** lleva existencia (se compra, se vende, se cuenta).
- **Servicio:** no lleva existencia. Siempre usa la unidad *Servicio* y puede tener **duración** (minutos), que propone la duración de las citas.
- **Kit:** un conjunto de productos. Al vender el kit sale la existencia de sus **componentes**.

## Crear un producto

**Productos → Nuevo producto.** Nombre, tipo, unidad (pieza, kg, litro…), categoría, marca, precio, costo, impuesto, código de barras (opcional, no se repite) y **stock mínimo** (avisa cuando la existencia llegue a ese número). Al crearlo puedes cargar una **existencia inicial** en la sucursal donde trabajas.

### Imágenes

Hasta **5 imágenes** por producto (JPG, PNG o WebP, hasta 8 MB cada una), tanto al crear como al editar: pulsa el cuadro **+** para agregar una a la vez. La primera es la principal (la que se ve en listas y en el catálogo). Las imágenes se limpian al subirlas (se quita la ubicación y otros datos de la cámara).

## La ficha del producto

- Datos, precio, costo promedio y existencias por sucursal.
- **Componentes** (si es kit).
- **Proveedores** que lo surten y su historial de costos.
- **Paquete o membresía** (si es servicio; ver abajo).
- Historial de cambios.

El **costo** se recalcula con cada compra como promedio ponderado con la existencia de todas las sucursales.

## Catálogos

**Productos → Catálogos** tiene una pestaña por catálogo: categorías, unidades, tipos, impuestos y marcas.

- Lo que se elimina ya no se puede elegir en productos nuevos y se puede restaurar.
- **Marcas:** el lápiz renombra la marca en todos sus productos. Si una marca está escrita de varias formas, **unifícalas**: los productos de las marcas marcadas pasan a la marca destino.

## Listas de precios

**Productos → Listas de precios.** Una lista (mayoreo, cliente frecuente…) define los precios que paga el cliente que la tiene asignada:

- Un **porcentaje** sobre el precio general (por ejemplo −10).
- **Precios por producto y cantidad** ("desde 12 piezas, $85"): gana el escalón más alto alcanzado.

La lista se asigna en la ficha del cliente o en una membresía. El punto de venta y las cotizaciones aplican el precio solos. Una lista solo se puede eliminar si ningún cliente la usa.

## Paquetes y membresías

En la ficha de un servicio, **Paquete o membresía**:

- **Paquete de sesiones:** el servicio que incluye, cuántas sesiones y, si se quiere, una vigencia en días.
- **Membresía:** su duración en días y, opcional, la lista de precios para sus miembros.

Se venden como cualquier producto, siempre a un cliente registrado. Ver [Clientes → Paquetes y membresías](clientes.md#paquetes-y-membresías).

## Eliminar

Al eliminar un producto deja de ofrecerse; las ventas y compras anteriores lo siguen mostrando.
